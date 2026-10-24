import hashlib

import pytest

from esaa.errors import ESAAError
from esaa.queries import format_query, list_activity, list_tasks
from esaa.service import ESAAService


def hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_queries_and_cursor_are_read_only(contract_bundle):
    s = ESAAService(contract_bundle)
    s.init(with_demo_tasks=True)
    before = hashes(contract_bundle)
    first = list_tasks(contract_bundle, limit=1)
    second = list_tasks(contract_bundle, limit=1, cursor=first["next_cursor"])
    assert first["tasks"][0]["task_id"] < second["tasks"][0]["task_id"]
    assert len(list_tasks(contract_bundle, statuses=["todo"], kind="impl")["tasks"]) == 1
    assert not list_tasks(contract_bundle, statuses=["done"])["tasks"]
    assert not list_tasks(contract_bundle, source="planned")["tasks"]
    events = list_activity(contract_bundle, hide_verify=True)
    assert all(not e["action"].startswith("verify.") for e in events["events"])
    assert list_activity(contract_bundle, actions=["claim"])["events"] == []
    assert "task_id" in format_query(first, "table")
    assert format_query(events, "jsonl").count("\n") == len(events["events"]) - 1
    assert hashes(contract_bundle) == before
    s.create_task("T-Z", task_kind="impl", title="new")
    with pytest.raises(ESAAError, match="start again"):
        list_tasks(contract_bundle, limit=1, cursor=first["next_cursor"])


@pytest.mark.parametrize("limit", [0, -1, 1001, True])
def test_invalid_limit(contract_bundle, limit):
    with pytest.raises(ESAAError):
        list_tasks(contract_bundle, limit=limit)


def test_bad_cursor_corruption_and_event_filters(contract_bundle):
    s = ESAAService(contract_bundle)
    s.init(with_demo_tasks=True)
    with pytest.raises(ESAAError):
        list_tasks(contract_bundle, cursor="!bad")
    s.claim_task("T-1010", actor="agent-impl")
    events = list_activity(contract_bundle, task_id="T-1010", actions=["claim"])["events"]
    assert len(events) == 1
    assert not list_activity(contract_bundle, after_seq=events[0]["event_seq"], actions=["claim"])["events"]
    p = contract_bundle / ".roadmap/activity.jsonl"
    p.write_text(p.read_text() + "bad\n")
    with pytest.raises(ESAAError):
        list_activity(contract_bundle)


def test_uninitialized_queries_do_not_create_files(tmp_path):
    before = hashes(tmp_path)
    for query in (list_tasks, list_activity):
        with pytest.raises(ESAAError, match="not initialized"):
            query(tmp_path)
        assert hashes(tmp_path) == before
        assert not (tmp_path / ".roadmap").exists()
