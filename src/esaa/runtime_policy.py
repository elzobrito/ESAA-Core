"""Attempt lifecycle (R2) — RF aplicada localmente pelo Orchestrator.

Le RUNTIME_POLICY.yaml e consulta o event store para decidir:
- esta tarefa atingiu max_attempts? (output.rejected events penalizantes)
- esta tarefa em cooldown? (rejeicao recente nas ultimas N segundos)
- esta tarefa em attempt expirado? (claim sem complete ha mais que TTL)

Sem estado em memoria: tudo derivavel do event store (event-sourced).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .errors import ESAAError

POLICY_REL_PATH = ".roadmap/RUNTIME_POLICY.yaml"
POLICY_SCHEMA_PATH = Path(__file__).resolve().parent / "templates" / "runtime_policy.schema.json"
_SEPARATION_ENFORCE = frozenset({"enforce", "on", "true", "strict"})
_SEPARATION_OFF = frozenset({"off", "false", "no", "disabled"})

DEFAULT_POLICY = {
    "attempt_lifecycle": {"ttl": "PT30M"},
    "attempt_limits": {
        "max_attempts_per_task": 3,
        "cooldown_between_attempts": "PT2M",
    },
}


def _policy_invalid(detail: str) -> ESAAError:
    return ESAAError("POLICY_INVALID", f"{POLICY_REL_PATH} {detail}"[:200])


@lru_cache(maxsize=1)
def _policy_validator() -> Draft202012Validator:
    """Schema distribuido com o pacote; workspaces existentes nao precisam de arquivo novo."""
    try:
        schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ESAAError("POLICY_INVALID", f"packaged policy schema is unavailable: {exc}") from exc
    return Draft202012Validator(schema)


def validate_policy(data: Any) -> dict[str, Any]:
    """AUD-O1-080 (FUN-01): falha fechado para chave desconhecida ou valor invalido.

    Chaves marcadas como reservadas no schema (x-esaa-reserved) sao aceitas e
    nao tem efeito nesta versao.
    """
    if not isinstance(data, dict):
        raise _policy_invalid("<root>: policy must be a mapping")
    errors = sorted(_policy_validator().iter_errors(data), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise _policy_invalid(f"{where}: {error.message.splitlines()[0][:140]}")
    return data


def load_policy(root: Path) -> dict[str, Any]:
    """Le e valida a politica do workspace. Ausente -> DEFAULT_POLICY; vazia -> {}."""
    path = root / ".roadmap" / "RUNTIME_POLICY.yaml"
    if not path.exists():
        return DEFAULT_POLICY
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or "invalid YAML"
        raise _policy_invalid(f"<root>: not valid YAML ({problem})") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise _policy_invalid(f"<root>: unreadable ({exc.__class__.__name__})") from exc
    return validate_policy({} if data is None else data)


_ISO_DUR = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_duration(s: str) -> timedelta:
    """ISO-8601 duration limitada a PT<H>H<M>M<S>S."""
    m = _ISO_DUR.match(s.strip())
    if not m:
        return timedelta(0)
    h, mn, sec = (int(x) if x else 0 for x in m.groups())
    return timedelta(hours=h, minutes=mn, seconds=sec)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def count_penalizing_rejections(events: list[dict[str, Any]], task_id: str) -> int:
    """Conta output.rejected events para a tarefa onde penalizes_counter != False.

    Por compatibilidade, o payload nao traz penalizes_counter; o codigo
    PRIOR_STATUS_MISMATCH e o unico nao-penalizante (per contract).
    """
    n = 0
    for e in events:
        if e.get("action") == "task.release" and (e.get("payload") or {}).get("task_id") == task_id:
            n = 0
        if e.get("action") != "output.rejected":
            continue
        p = e.get("payload") or {}
        if p.get("task_id") != task_id:
            continue
        if p.get("error_code") == "PRIOR_STATUS_MISMATCH":
            continue
        n += 1
    return n


def last_rejection_ts(events: list[dict[str, Any]], task_id: str) -> datetime | None:
    last = None
    for e in events:
        if e.get("action") == "task.release" and (e.get("payload") or {}).get("task_id") == task_id:
            last = None
        if e.get("action") != "output.rejected":
            continue
        p = e.get("payload") or {}
        if p.get("task_id") != task_id:
            continue
        try:
            last = _parse_ts(e["ts"])
        except Exception:
            continue
    return last


def is_in_cooldown(events: list[dict[str, Any]], task_id: str, now: datetime, cooldown: timedelta) -> bool:
    ts = last_rejection_ts(events, task_id)
    if ts is None:
        return False
    return (now - ts) < cooldown


def is_blocked_by_max_attempts(events: list[dict[str, Any]], task_id: str, max_attempts: int) -> bool:
    return count_penalizing_rejections(events, task_id) >= max_attempts


def resolve_role(actor: str, root: Path | None = None) -> str:
    """FIX-1807 — Resolve role de um actor.

    Consulta .roadmap/agents_swarm.yaml se existir: agents[<actor>].role.
    Fallback heuristico: prefixo 'agent-qa*' -> 'qa'; 'agent-orchestrator*' -> 'orchestrator';
    outros -> 'agent'.
    """
    if root is not None:
        swarm_path = root / ".roadmap" / "agents_swarm.yaml"
        if swarm_path.exists():
            try:
                data = yaml.safe_load(swarm_path.read_text(encoding="utf-8")) or {}
                role = (data.get("agents", {}).get(actor, {}) or {}).get("role")
                if role:
                    role_value = str(role)
                    return "qa" if role_value == "quality" else role_value
            except Exception:
                pass
    if actor.startswith("agent-qa"):
        return "qa"
    if actor.startswith("agent-orchestrator") or actor == "orchestrator":
        return "orchestrator"
    return "agent"


def runner_validation_mode(policy: dict[str, Any]) -> str:
    """G08/PROV-02: permissive (default) ou strict. Valor desconhecido falha fechado."""
    val = policy.get("runner_validation", "permissive")
    if val not in {"permissive", "strict"}:
        raise _policy_invalid(f"runner_validation: {val!r} is not one of ['permissive', 'strict']")
    return str(val)


def known_runners(root: Path) -> set[str]:
    """Runners registrados na secao `runners:` de agents_swarm.yaml."""
    swarm_path = root / ".roadmap" / "agents_swarm.yaml"
    if not swarm_path.exists():
        return set()
    try:
        data = yaml.safe_load(swarm_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    runners = data.get("runners", {}) or {}
    return {str(k) for k in runners} if isinstance(runners, dict) else set()


def runner_kind(root: Path, runner_id: str) -> str | None:
    """`kind` declarado para o runner em agents_swarm.yaml (None se nao registrado)."""
    swarm_path = root / ".roadmap" / "agents_swarm.yaml"
    if not swarm_path.exists():
        return None
    try:
        data = yaml.safe_load(swarm_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    runners = data.get("runners", {}) or {}
    entry = runners.get(runner_id) if isinstance(runners, dict) else None
    kind = entry.get("kind") if isinstance(entry, dict) else None
    return str(kind) if kind else None


def require_operator_runner(root: Path, command: str) -> None:
    """AUD-O0-040 (GOV-03/GOV-04): comandos de operador exigem runner humano em modo strict.

    Com runner_validation=strict, o runner corrente precisa estar registrado em
    agents_swarm.yaml com kind=human. Em permissive (default) nada muda. O
    runner_id e autodeclarado: a regra separa papeis e evita que um runner de
    agente use comandos administrativos por engano; nao substitui a identidade
    assinada do proprietario.
    """
    if runner_validation_mode(load_policy(root)) != "strict":
        return
    from .provenance import resolve_runner

    runner_id = str(resolve_runner()["runner_id"])
    kind = runner_kind(root, runner_id)
    if kind != "human":
        raise ESAAError(
            "OPERATOR_REQUIRED",
            f"{command} is an operator command; runner {runner_id} (kind={kind or 'unregistered'}) "
            "is not a human runner (runner_validation=strict)",
        )


def validate_runner_id(runner_id: str, root: Path, policy: dict[str, Any]) -> None:
    """Em modo strict, runner_id deve estar registrado no swarm."""
    if runner_validation_mode(policy) != "strict":
        return
    if runner_id not in known_runners(root):
        raise ESAAError("RUNNER_UNKNOWN", f"runner not registered in agents_swarm.yaml: {runner_id}")


def review_authorization_mode(policy: dict[str, Any]) -> str:
    """FIX-1807 — modo de autorizacao para review: 'owner' (legado) ou 'qa_role'."""
    val = policy.get("review_authorization", "owner")
    if val not in {"owner", "qa_role"}:
        raise _policy_invalid(f"review_authorization: {val!r} is not one of ['owner', 'qa_role']")
    return str(val)


def review_runner_separation_mode(policy: dict[str, Any]) -> str:
    """AUD-O0-020 (GOV-01): 'off' (default, comportamento historico) ou 'enforce'.

    Opt-in do operador em RUNTIME_POLICY.yaml. Vale apenas no modo legado com
    review_authorization=qa_role; com identidade ativa a separacao e garantida
    por principal assinado.
    """
    raw = policy.get("review_runner_separation", "off")
    val = str(raw).strip().lower() if isinstance(raw, (str, bool)) else ""
    if val in _SEPARATION_ENFORCE:
        return "enforce"
    if val in _SEPARATION_OFF:
        return "off"
    raise _policy_invalid(
        f"review_runner_separation: {raw!r} is not one of {sorted(_SEPARATION_ENFORCE | _SEPARATION_OFF)}"
    )


def assert_review_runner_separation(
    events: list[dict[str, Any]], task_id: str, reviewer_runner_id: str
) -> None:
    """Rejeita review cujo runner executou o claim ou o complete vigentes da tarefa.

    O nome do actor e autodeclarado no modo legado; o runner tambem, mas exigir
    runners distintos impede que uma unica sessao conclua e aprove trocando
    apenas --actor. Eventos historicos sem bloco runner nao sao comparaveis e
    nao bloqueiam a revisao.
    """
    executors: dict[str, str] = {}
    for event in events:
        if event.get("action") not in {"claim", "complete"}:
            continue
        if (event.get("payload") or {}).get("task_id") != task_id:
            continue
        runner_id = (event.get("runner") or {}).get("runner_id")
        if isinstance(runner_id, str) and runner_id.strip():
            executors[str(event["action"])] = runner_id.strip()
        else:
            executors.pop(str(event["action"]), None)
    reviewer = reviewer_runner_id.strip()
    matched = sorted(action for action, runner_id in executors.items() if runner_id == reviewer)
    if matched:
        raise ESAAError(
            "SELF_REVIEW_FORBIDDEN",
            f"runner {reviewer} performed {'/'.join(matched)} of task {task_id}; "
            "review requires a different runner (policy review_runner_separation)",
        )


def attempt_expired(events: list[dict[str, Any]], task_id: str, now: datetime, ttl: timedelta) -> bool:
    """Tarefa em in_progress sem complete ha mais que ttl?"""
    last_claim = None
    last_complete = None
    for e in events:
        p = e.get("payload") or {}
        if p.get("task_id") != task_id:
            continue
        act = e.get("action")
        if act == "claim":
            try:
                last_claim = _parse_ts(e["ts"])
            except Exception:
                pass
        elif act == "complete":
            try:
                last_complete = _parse_ts(e["ts"])
            except Exception:
                pass
    if last_claim is None:
        return False
    if last_complete is not None and last_complete >= last_claim:
        return False
    return (now - last_claim) > ttl
