import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parents[1] / "src/esaa/templates/agent_result.schema.json"


def validator():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def envelope(effect, action="complete"):
    return {
        "activity_event": (
            {
                "action": action,
                "task_id": "T",
                "prior_status": "in_progress" if action == "complete" else "todo",
                "verification": {"checks": ["a", "b"]},
            }
            if action == "complete"
            else {"action": action, "task_id": "T", "prior_status": "todo"}
        ),
        "file_updates": [effect],
    }


def binary():
    return {
        "path": "build/reference.mkv",
        "binary": {"source": "input/reference.mkv", "size": 2162463, "sha256": "a" * 64},
    }


def test_binary_and_legacy_text_variants():
    v = validator()
    assert v.is_valid(envelope(binary()))
    assert v.is_valid(envelope({"path": "src/file.txt", "content": "texto"}))
    assert v.is_valid(
        envelope(
            {
                "path": "src/file.txt",
                "base_sha256": "0" * 64,
                "edits": [{"old_string": "a", "new_string": "b"}],
            }
        )
    )


@pytest.mark.parametrize("mutation", ["hash", "boolean", "negative", "extra", "mixed"])
def test_reject_invalid_binary_metadata(mutation):
    effect = binary()
    if mutation == "hash":
        effect["binary"]["sha256"] = "bad"
    if mutation == "boolean":
        effect["binary"]["size"] = True
    if mutation == "negative":
        effect["binary"]["size"] = -1
    if mutation == "extra":
        effect["binary"]["extra"] = "x"
    if mutation == "mixed":
        effect["content"] = "x"
    assert not validator().is_valid(envelope(effect))


def test_binary_not_valid_on_claim():
    assert not validator().is_valid(envelope(binary(), "claim"))
