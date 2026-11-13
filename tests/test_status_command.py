"""The status summary is bounded, authoritative, and read-only."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from esaa import cli, status
from esaa.events import make_event
from esaa.projector import materialize
from esaa.service import ESAAService
from esaa.store import parse_event_store, save_issues, save_lessons, save_roadmap

KEYS = [
    "last_event_seq",
    "verify_status",
    "chain_status",
    "projections_stale",
    "tasks_by_status",
    "review_queue",
    "eligible",
    "stale_claims",
    "open_issues_by_severity",
    "open_issues",
]
NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


def _events(root, actions):
    """Write a synthetic event fixture; production summary must never write it."""
    events = parse_event_store(root)
    for action, actor, payload, ts in actions:
        event = make_event(len(events) + 1, actor, action, payload)
        event["ts"] = ts
        events.append(event)
    (root / ".roadmap/activity.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    roadmap, issues, lessons = materialize(events)
    save_roadmap(root, roadmap)
    save_issues(root, issues)
    save_lessons(root, lessons)


def _task(task_id, title=None):
    return {
        "task_id": task_id,
        "task_kind": "impl",
        "title": title or task_id,
        "outputs": {"files": [f"src/{task_id}.txt"]},
    }


def _workspace(root):
    service = ESAAService(root)
    service.init(force=True)
    return service


def _hashes(root):
    return {
        name: hashlib.sha256((root / ".roadmap" / name).read_bytes()).hexdigest()
        for name in ("activity.jsonl", "roadmap.json", "issues.json", "lessons.json")
    }


def test_empty_initialized_workspace(contract_bundle):
    _workspace(contract_bundle)
    result = status.build_status(contract_bundle, now=NOW)
    assert list(result) == KEYS
    assert result["tasks_by_status"] == dict.fromkeys(("todo", "in_progress", "review", "done"), 0)
    assert result["verify_status"] == "ok"
    assert result["chain_status"] == "unanchored"
    assert result["projections_stale"] is False
    assert all(result[key] == [] for key in ("review_queue", "eligible", "stale_claims", "open_issues"))
    assert "(none)" in status.render_status_table(result)


def test_each_status_and_review_completion_events(contract_bundle):
    _workspace(contract_bundle)
    actions = [
        ("task.create", "orchestrator", _task(task_id), "2026-11-12T08:00:00Z")
        for task_id in ("TODO", "ACTIVE", "REVIEW", "DONE", "OLDER")
    ]
    actions += [
        ("claim", "worker", {"task_id": task_id}, "2026-11-12T09:00:00Z")
        for task_id in ("ACTIVE", "REVIEW", "DONE", "OLDER")
    ]
    actions += [
        ("complete", "worker", {"task_id": "REVIEW"}, "2026-11-12T11:00:00Z"),
        ("complete", "worker", {"task_id": "OLDER"}, "2026-11-12T10:30:00+01:00"),
        ("complete", "worker", {"task_id": "DONE"}, "2026-11-12T10:00:00Z"),
        ("review", "worker", {"task_id": "DONE", "decision": "approve"}, "2026-11-12T11:00:00Z"),
    ]
    _events(contract_bundle, actions)
    result = status.build_status(contract_bundle, now=NOW)
    assert result["tasks_by_status"] == {"todo": 1, "in_progress": 1, "review": 2, "done": 1}
    assert result["eligible"] == [{"task_id": "TODO", "title": "TODO"}]
    assert [row["task_id"] for row in result["review_queue"]] == ["OLDER", "REVIEW"]
    assert result["review_queue"][0] == {
        "task_id": "OLDER",
        "title": "OLDER",
        "completed_by": "worker",
        "completed_at": "2026-11-12T10:30:00+01:00",
        "waiting_seconds": 9000,
    }
    assert result["stale_claims"] == [
        {
            "task_id": "ACTIVE",
            "assigned_to": "worker",
            "started_at": "2026-11-12T09:00:00Z",
            "age_seconds": 10800,
        }
    ]


def test_claim_ttl_boundary_and_policy(contract_bundle):
    _workspace(contract_bundle)
    _events(
        contract_bundle,
        [
            ("task.create", "orchestrator", _task("A"), "2026-11-12T09:00:00Z"),
            ("claim", "worker", {"task_id": "A"}, "2026-11-12T11:30:00Z"),
        ],
    )
    assert status.build_status(contract_bundle, now=NOW)["stale_claims"] == []
    assert len(status.build_status(contract_bundle, now=NOW + timedelta(seconds=1))["stale_claims"]) == 1
    (contract_bundle / ".roadmap/RUNTIME_POLICY.yaml").write_text('attempt_lifecycle:\n  ttl: "PT2H"\n')
    assert status.build_status(contract_bundle, now=NOW + timedelta(seconds=1))["stale_claims"] == []


def test_open_issues_sorted_and_resolved_excluded(contract_bundle):
    _workspace(contract_bundle)
    actions = [
        (
            "issue.report",
            "worker",
            {"issue_id": f"I-{index:02}", "severity": severity, "title": f"issue {index}"},
            "2026-11-12T09:00:00Z",
        )
        for index, severity in enumerate(["low", "medium", "high", "critical"] * 4)
    ]
    actions.append(("issue.resolve", "orchestrator", {"issue_id": "I-03"}, "2026-11-12T10:00:00Z"))
    _events(contract_bundle, actions)
    result = status.build_status(contract_bundle, now=NOW)
    assert result["open_issues_by_severity"] == {"critical": 3, "high": 4, "medium": 4, "low": 4}
    assert len(result["open_issues"]) == 10
    assert [issue["severity"] for issue in result["open_issues"]] == ["critical"] * 3 + ["high"] * 4 + [
        "medium"
    ] * 3
    assert "I-03" not in [issue["issue_id"] for issue in result["open_issues"]]


def test_cli_json_table_help_and_read_only(contract_bundle, capsys, monkeypatch):
    service = _workspace(contract_bundle)
    before = _hashes(contract_bundle)
    monkeypatch.setattr(
        "esaa.store._acquire_store_lock", lambda *args, **kwargs: pytest.fail("read acquired lock")
    )
    assert cli.main(["--root", str(contract_bundle), "status", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert list(result) == KEYS
    assert result["eligible"] == service.eligible()["eligible"]
    assert cli.main(["--root", str(contract_bundle), "status"]) == 0
    assert capsys.readouterr().out.startswith("ESAA status")
    assert _hashes(contract_bundle) == before
    with pytest.raises(SystemExit) as exc:
        cli.main(["status", "--help"])
    assert exc.value.code == 0
    assert "output format (default: table)" in capsys.readouterr().out


def test_single_log_read_and_materialization(contract_bundle, monkeypatch):
    _workspace(contract_bundle)
    calls = {"parse": 0, "materialize": 0}
    parse, project = status.parse_event_store, status.materialize

    def read(root):
        calls["parse"] += 1
        return parse(root)

    def materialize_once(events):
        calls["materialize"] += 1
        return project(events)

    monkeypatch.setattr(status, "parse_event_store", read)
    monkeypatch.setattr(status, "materialize", materialize_once)
    status.build_status(contract_bundle)
    assert calls == {"parse": 1, "materialize": 1}


def test_projection_freshness_and_recorded_verification(contract_bundle, capsys):
    _workspace(contract_bundle)
    _events(
        contract_bundle,
        [("verify.fail", "orchestrator", {"verify_status": "mismatch"}, "2026-11-12T11:00:00Z")],
    )
    path = contract_bundle / ".roadmap/roadmap.json"
    projected = json.loads(path.read_text())
    projected["meta"]["run"]["last_event_seq"] -= 1
    path.write_text(json.dumps(projected))
    result = status.build_status(contract_bundle)
    assert result["verify_status"] == "mismatch"
    assert result["projections_stale"] is True
    assert cli.main(["--root", str(contract_bundle), "status", "--format", "json"]) == 2
    capsys.readouterr()
    path.unlink()
    assert status.build_status(contract_bundle)["projections_stale"] is True


def test_bounded_table_many_rows_and_long_titles(contract_bundle):
    _workspace(contract_bundle)
    result = status.build_status(contract_bundle)
    result.update(
        {
            "review_queue": [
                {
                    "task_id": f"R-{i}",
                    "title": "X" * 300,
                    "completed_by": "worker",
                    "completed_at": "2026-11-12T10:00:00Z",
                    "waiting_seconds": 7200,
                }
                for i in range(30)
            ],
            "eligible": [{"task_id": f"E-{i}", "title": "\n\tLong " + "X" * 300} for i in range(30)],
            "stale_claims": [
                {
                    "task_id": f"S-{i}",
                    "assigned_to": "worker",
                    "started_at": "2026-11-12T09:00:00Z",
                    "age_seconds": 10800,
                }
                for i in range(30)
            ],
            "open_issues": [
                {"issue_id": f"I-{i}", "severity": "high", "title": "X" * 300} for i in range(10)
            ],
        }
    )
    lines = status.render_status_table(result).splitlines()
    assert len(lines) <= 40
    assert max(map(len, lines)) <= 100
    assert sum("mais)" in line for line in lines) == 4
    assert "  (+22 mais)" in lines
    assert "..." in "\n".join(lines)


def test_timestamp_fallbacks():
    assert status._age_seconds(None, NOW) is None
    assert status._age_seconds("invalid", NOW) is None
    assert status._age_seconds("2026-11-12T11:00:00", NOW) is None
    assert status._age_seconds("2026-11-12T13:00:00Z", NOW) == 0


def test_real_repository_performance(live_identity_pin):
    start = perf_counter()
    result = status.build_status(live_identity_pin)
    assert perf_counter() - start < 5
    assert result["last_event_seq"] > 0
    lines = status.render_status_table(result).splitlines()
    assert len(lines) <= 40
    assert max(map(len, lines)) <= 100


def test_planned_tasks_counted_like_task_list(contract_bundle):
    from esaa.queries import list_tasks

    service = _workspace(contract_bundle)
    (contract_bundle / ".roadmap/roadmap.planned.json").write_text(
        json.dumps({"tasks": [_task("PLANNED")]}), encoding="utf-8"
    )
    result = status.build_status(contract_bundle)
    assert result["tasks_by_status"]["todo"] == list_tasks(contract_bundle)["total"] == 1
    assert result["eligible"] == [
        {"task_id": task["task_id"], "title": task["title"]} for task in service.eligible()["eligible"]
    ]


def test_latest_complete_after_requested_changes(contract_bundle):
    _workspace(contract_bundle)
    _events(
        contract_bundle,
        [
            ("task.create", "orchestrator", _task("A"), "2026-11-12T08:00:00Z"),
            ("claim", "worker", {"task_id": "A"}, "2026-11-12T09:00:00Z"),
            ("complete", "worker", {"task_id": "A"}, "2026-11-12T10:00:00Z"),
            ("review", "worker", {"task_id": "A", "decision": "request_changes"}, "2026-11-12T10:30:00Z"),
            ("complete", "worker", {"task_id": "A"}, "2026-11-12T11:00:00Z"),
        ],
    )
    result = status.build_status(contract_bundle, now=NOW)
    assert result["review_queue"][0]["completed_at"] == "2026-11-12T11:00:00Z"
    assert result["review_queue"][0]["waiting_seconds"] == 3600


def test_review_order_with_future_completions(contract_bundle):
    _workspace(contract_bundle)
    _events(
        contract_bundle,
        [
            ("task.create", "orchestrator", _task("A"), "2026-11-12T08:00:00Z"),
            ("task.create", "orchestrator", _task("Z"), "2026-11-12T08:00:00Z"),
            ("claim", "worker", {"task_id": "A"}, "2026-11-12T09:00:00Z"),
            ("claim", "worker", {"task_id": "Z"}, "2026-11-12T09:00:00Z"),
            ("complete", "worker", {"task_id": "A"}, "2026-11-12T14:00:00Z"),
            ("complete", "worker", {"task_id": "Z"}, "2026-11-12T13:00:00Z"),
        ],
    )
    rows = status.build_status(contract_bundle, now=NOW)["review_queue"]
    assert [row["task_id"] for row in rows] == ["Z", "A"]
    assert [row["waiting_seconds"] for row in rows] == [0, 0]


def test_table_limits_wide_unicode_columns():
    import unicodedata

    for text in ("界" * 300, "x" * 96 + "界" * 100):
        line = status._line(text)
        assert line.endswith("...")
        assert sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in line) <= 100
