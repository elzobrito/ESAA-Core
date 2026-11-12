# Custo de leitura do activity.jsonl — proposta do Fable

**Veredito:** no commit lido, o custo quadrático já foi removido (b26), e `claim`/`submit` fazem 2 leituras e 2 replays, não os "4 a 6" que afirmei antes. O que resta é custo linear repetido: `complete` e `review` ainda refazem replays desnecessários, e todo comando de leitura decodifica o log inteiro. Não executei nada (Python segue negado), então diffs e script abaixo não foram testados.

Eu havia atribuído ao `submit` os `materialize` de `submission.py:367-439`; eles pertencem a `_accept_agent_output`, usado só por `esaa run`.

## 1. Diagnóstico

**Antes de tudo, confira a versão** nos workspaces lentos com `esaa --version`:
- A auditoria de 10/11 mediu, com 50 mil eventos, `verify` em 22 s e `claim` em 75 s (`docs/audit/ESAA-CORE-AUDIT-2026-11-10.md:152`) **[V]**.
- O CHANGELOG da 0.5.0b26 registra cerca de 2 s e 3 s depois da correção **[V]**.
- Se a dor vem de versão anterior à b26, atualizar é a correção.

**Unidades de custo [V]:**
- **R** é `store.py:parse_event_store` (242-335): lê o arquivo todo, calcula SHA-256, faz `json.loads` de todas as linhas e valida evento a evento. Na segunda chamada do mesmo processo a validação é pulada, mas a leitura e a decodificação se repetem (267-270).
- **P** é um replay completo desde o evento 1 (`projector.py:replay_state`, 476).

| Comando | R | P | Onde | Varreduras extras do log |
|---|---|---|---|---|
| `state` | 1 | 1 | `task_admin.py:153,155` | — |
| `activity list` | 1 | 0 | `queries.py:20` | filtra todos os eventos, mesmo com `--after-seq` |
| `dispatch-context` | 1 | 1 | `task_admin.py:171-173` | cópia profunda das views; perfil |
| `verify` | 1 | 1 | `service_core.py:227-229` | lê e normaliza 3 projeções (`projection_check.py:50`) |
| `eligible` | 1 | 1 | `execution.py:66,68` | 2 varreduras por tarefa elegível (`execution.py:105,109`) |
| `claim` / `submit` | 2 | 2 | `submission.py:129,133`; `store.py:586,587` | releitura total em `_verify_appended_lines` (`store.py:482`) |
| `review` | 3 | 3 | o anterior + `task_admin.py:290` | — |
| `complete` | 3 | 5 ou 6 | o do `claim` + `task_admin.py:249`; `verification_gate.py:24,94`; `limit_revalidation.py:19` (só com `file_updates`) | — |
| `task create` | 2 | 4 | `task_admin.py:79,80,118`; `store.py:586,587`; `orchestrator_commit.py:20` | — |

Outros custos por comando:
- **Escrita:** cada uma serializa a lista de tarefas 4 vezes para o hash da projeção e regrava o `roadmap.json` inteiro (`store.py:642`) **[V]**.
- **Ciclo de tarefa:** `eligible`, `dispatch-context`, `claim`, `complete`, `review` e três `verify` somam 13 R e 16 P **[V na contagem]**. Isso dá algo como 20 s por tarefa a 50 mil eventos **[S, extrapolado dos 2 a 3 s do CHANGELOG]**.
- **Memória:** cada R materializa todos os eventos como objetos Python; a 500 mil eventos estimo mais de 1 GB por leitura **[S]**.

## 2. Solução em camadas

### Camada 1 — Eliminar replays redundantes

- **Desenho:** reaproveitar a tarefa e o estado que o comando já tem.
- **Ganho [S]:** `complete` cai de 3R+6P para 2R+3P; `review`, de 3R+3P para 2R+2P.
- **Risco de integridade:** nenhum; as validações são as mesmas.
- **Testes:** `tests/test_replay_performance.py` já tem os testes de equivalência; acrescente um contador de `replay_state` por comando via monkeypatch.

```diff
# verification_gate.py
-def validate_evidence(root, events, actor, candidate):
+def validate_evidence(root, events, actor, candidate, task=None):
     activity = candidate.get("activity_event", {})
     if activity.get("action") != "complete":
         return None
-    task = next((t for t in materialize(events)[0]["tasks"] if t["task_id"] == activity.get("task_id")), None)
+    if task is None:
+        task = next((t for t in materialize(events)[0]["tasks"] if t["task_id"] == activity.get("task_id")), None)
@@ validate_pending
     prefix = list(events)
+    state = replay_state(events)          # um replay, não um por complete
     ...
-            task = next((t for t in materialize(prefix)[0]["tasks"] if t["task_id"] == task_id), None)
+            task = next((t for t in state_tasks(state) if t["task_id"] == task_id), None)
     ...
-                prepared = cast(dict[str, Any], validate_evidence(root, prefix, event["actor"], candidate))
+                prepared = cast(dict[str, Any], validate_evidence(root, prefix, event["actor"], candidate, task=task))
         prefix.append(event)
+        apply_events(state, [event])
# submission.py:167
-            validate_evidence(self.root, events, actor, agent_output)
+            validate_evidence(self.root, events, actor, agent_output, task=task)
# task_admin.py:290 (review)
-        previous_status = self.task_state(task_id)["task"]["status"]
 ...
-            and previous_status == "review"
+            and result.get("status") == "accepted"   # o submit já exige prior_status=review
```

Itens na mesma linha, sem diff:
- Em `complete`, resolver `issue_id` e `fixes` dentro do `submit`, em vez do `task_state` prévio (`task_admin.py:249`).
- Em `eligible`, contar as rejeições numa passada única.
- Em `_verify_appended_lines`, reler só os bytes anexados.

### Camada 2 — Leituras confiando na projeção, com conferência barata

- **Desenho:** arquivo derivado `.roadmap/.cache/head.json`, gravado por último em `append_transactional` e em `project`.
  - Guarda o tamanho e o SHA-256 dos bytes do log, o `last_event_seq` e o SHA-256 de cada projeção.
  - `state`, `dispatch-context` e `task list` leem os bytes do log sem decodificar e conferem tamanho e hash.
  - Se tudo confere, servem `roadmap.json`, `issues.json` e `lessons.json` direto.
  - Qualquer divergência cai no caminho atual.
- **`activity list`:** com o head válido, decodifica só as linhas a partir de `after_seq` e para em `limit+1`. O `event_seq` equivale ao número da linha **[V, `store.py:301`]**.
- **Ganho [S]:** leituras passam de cerca de 2 s para 0,3 a 0,5 s a 50 mil eventos, e ficam abaixo de 1 s a 500 mil.
- **Risco:** o hash é do log inteiro, então edição no meio do arquivo invalida o cache; tamanho e mtime sozinhos não bastariam.
  - Quem forjar log, projeções e head juntos engana as leituras, mas `esaa verify` continua fazendo replay completo e detecta.
  - Isso contraria a regra declarada em `queries.py:1` ("never trust cached projections"); é decisão do Elzo.
  - Com pin ou identidade ativos, o atalho deve se desligar, porque essa validação depende de arquivos externos (`store.py:229`) **[V]**.
- **Invalidação:** falha de escrita entre o append e o head deixa o tamanho divergente, e o próximo comando faz o caminho completo. Apagar o head é sempre seguro.
- **Testes:**
  - Saída idêntica com e sem head no `_rich_history`.
  - Cada adulteração cai no caminho completo: linha extra, byte trocado com o mesmo tamanho, `roadmap.json` editado, head ausente.
  - Com head válido, `parse_event_store` não é chamado.

```python
# store.py (esboço)
def trusted_views(root):
    try:
        head = json.loads((root / ".roadmap/.cache/head.json").read_bytes())
        data = (root / EVENT_STORE_PATH).read_bytes()
        if len(data) != head["store_size"] or hashlib.sha256(data).hexdigest() != head["store_sha256"]:
            return None
        views = {}
        for name, digest in head["views_sha256"].items():
            raw = (root / ".roadmap" / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                return None
            views[name] = json.loads(raw)
        return views
    except (OSError, ValueError, KeyError):
        return None
```

### Camada 3 — Parar de emitir `verify.start` e `verify.ok`

- **Desenho:** chave de política; o projetor continua aceitando os eventos antigos. O `verify_status` passa a ser definido na gravação da projeção; ele já fica fora do hash **[V, `projector.py:397`]**.
- **Pontos de emissão [V]:** `submission.py:227-255`, `orchestrator_commit.py:41-52`, `service_core.py:163-173`, `execution.py:417-430` e `activity_admin.py:85-95`.
- **Ganho [V na proporção]:** cada escrita grava 1 evento em vez de 3; logs novos crescem cerca de 2,5 vezes menos. Não acelera logs existentes.
- **Risco:** `snapshot.py:36` usa o último `verify.ok`. A auditoria (FUN-04) sugere um `projection_hash_after` conferido no replay; conferir em todo lote recalcularia o hash das tarefas a cada lote e traria o custo quadrático de volta.
- **Testes:** os que esperam o par `verify.*` (por exemplo, os de `scenarios.py`) precisam das duas variantes.

### Camada 4 — Estado-base mais cauda (AUD-O2-040), só depois

- **Desenho:** guardar offset, `last_seq`, hash do prefixo e estado serializado, e aplicar só a cauda.
- **Por que é grande:** os chamadores recebem a lista completa de eventos e a varrem para contar rejeições, achar principals e runners por tarefa, montar o registro de atores e nonces, o perfil, a configuração de verificação e a cadeia de hash **[V]**. O checkpoint teria de carregar todos esses agregados.
- **Limite:** o `roadmap.json` cresce com o número de tarefas e é regravado a cada escrita; a 500 mil eventos esse termo também pesa.

### Não recomendo agora

- **Rotação do log:** muda a semântica do log canônico.
- **Índice auxiliar ou SQLite:** a camada 2 já cobre as leituras.
- **Leitura em streaming:** economiza memória, não tempo.

## 3. Benchmark

O gerador replica o do teste de aceite existente (`tests/test_replay_performance.py:460`). Rode na raiz do repositório, antes e depois de cada camada.

```python
# bench_esaa.py — uso: PYTHONPATH=src python -B bench_esaa.py --events 50000
import argparse, json, os, resource, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from esaa.events import make_event
from esaa.service import ESAAService
from esaa.store import append_events

SKIP = {"activity.jsonl", "roadmap.json", "issues.json", "lessons.json", "project_profile.json"}

def build(root: Path, repo: Path, total: int) -> int:
    (root / ".roadmap").mkdir(parents=True)
    for f in (repo / ".roadmap").iterdir():
        if f.is_file() and f.name not in SKIP and not f.name.endswith(".lock"):
            shutil.copy2(f, root / ".roadmap" / f.name)
    ev = [make_event(1, "orchestrator", "run.start", {"run_id": "R", "status": "initialized"})]
    i = 0
    while len(ev) + 7 <= total:
        i += 1
        t = f"T-{i:06d}"
        ev += [
            make_event(1, "orchestrator", "task.create", {"task_id": t, "task_kind": "impl", "title": t,
                "description": "d" * 200, "depends_on": [], "targets": [], "outputs": {"files": [f"src/{t}.txt"]}}),
            make_event(1, "agent-impl", "claim", {"action": "claim", "task_id": t, "prior_status": "todo"}),
            make_event(1, "agent-impl", "complete", {"action": "complete", "task_id": t,
                "prior_status": "in_progress", "verification": {"checks": ["c"]}}),
            make_event(1, "orchestrator", "verify.start", {"strict": True}),
            make_event(1, "orchestrator", "verify.ok", {"projection_hash_sha256": "x"}),
            make_event(1, "agent-qa", "review", {"action": "review", "task_id": t, "prior_status": "review",
                "decision": "approve", "tasks": [t], "_reviewer_role": "qa"}),
        ]
    ev.append(make_event(1, "orchestrator", "task.create", {"task_id": "T-NEXT", "task_kind": "impl",
        "title": "next", "outputs": {"files": ["src/next.txt"]}}))
    for seq, e in enumerate(ev, 1):
        e["event_seq"], e["event_id"] = seq, f"EV-{seq:08d}"
    append_events(root, ev)
    ESAAService(root).project()
    return len(ev)

def run(root: Path, env: dict, *cmd: str, repeat: int = 1) -> None:
    best, code = None, 0
    for _ in range(repeat):
        t0 = time.perf_counter()
        p = subprocess.run([sys.executable, "-B", "-m", "esaa", "--root", str(root), *cmd],
                           env=env, capture_output=True, text=True)
        dt = time.perf_counter() - t0
        best, code = (dt if best is None else min(best, dt)), p.returncode
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
    print(f"{' '.join(cmd):45s} {best:7.2f}s  exit={code}  pico_rss_ate_aqui={rss}MB")
    if code:
        print("   ", p.stderr.strip()[:300])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=50_000)
    a = ap.parse_args()
    repo = Path.cwd()
    root = Path(tempfile.mkdtemp(prefix="esaa-bench-"))
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    n = build(root, repo, a.events)
    size = (root / ".roadmap/activity.jsonl").stat().st_size
    print(f"workspace={root} eventos={n} log={size/1e6:.1f}MB")
    run(root, env, "--version")                       # piso: só o start do Python
    for c in (("state", "T-NEXT"), ("dispatch-context", "T-NEXT"), ("eligible",), ("verify",),
              ("task", "list", "--limit", "10"),
              ("activity", "list", "--after-seq", str(n - 50), "--limit", "50", "--format", "table")):
        run(root, env, *c, repeat=3)
    run(root, env, "claim", "T-NEXT", "--actor", "agent-impl")
    run(root, env, "complete", "T-NEXT", "--actor", "agent-impl", "--check", "unit")
    run(root, env, "review", "T-NEXT", "--actor", "agent-qa", "--decision", "approve")
    run(root, env, "verify")
```

- **Escalas:** rode com `--events 50000`, `200000` e `500000`. A geração de 500 mil deve levar minutos e gigabytes de memória **[S]**.
- **Escritas:** são medidas uma vez, porque mudam o estado.
- **Piso:** a linha `--version` dá o custo fixo do Python; subtraia das demais.
- **Flag não conferida:** não li a definição de `task list --limit` na CLI. Se ela falhar, o `exit` e o stderr aparecem na saída.

## 4. Recomendação

**Mínimo para a semana que vem:**
1. Conferir a versão e rodar o benchmark, para ter a linha de base.
2. Camada 1, para as escritas.
3. Camada 2, para as leituras, que são a maior parte do que um agente executa.
4. Decidir sobre a camada 3; é a que mais reduz o crescimento futuro por linha alterada.

**Resultado esperado [S]:**
- A 50 mil eventos, leituras abaixo de 0,5 s e escritas entre 2 e 3 s.
- A 500 mil, só as leituras ficam folgadas. As escritas continuam lineares, na casa de 20 a 30 s e mais de 1 GB de memória.

Folga de escrita até 500 mil eventos só vem com a camada 4. Eu a deixaria para quando o benchmark mostrar escrita acima de uns 3 s num log real. Com a camada 3 ligada, esse ponto chega 2,5 vezes mais tarde.