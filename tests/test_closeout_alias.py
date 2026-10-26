"""Actor registration cannot replace an owner-bound alias namespace."""

from __future__ import annotations

import json
import os

import pytest
from test_actor_registration import _activated, _key, _register_auth
from test_canonical_identity import _bind

from esaa.cli import main
from esaa.errors import ESAAError
from esaa.events import make_event
from esaa.store import append_events, next_event_seq, parse_event_store


def _setup(root, repo):
    svc, keys = _activated(root, repo)
    _bind(svc, keys, "agent-spec", "alias-existing")
    _private, public = _key()
    auth = _register_auth(
        keys["owner"], keys["project_id"], os.urandom(16).hex(), "alias-existing", "qa", public
    )
    return svc, keys, public, auth


@pytest.mark.parametrize("dry_run", [True, False])
def test_actor_cannot_shadow_alias(tmp_path, repo_root, dry_run):
    svc, _keys, public, auth = _setup(tmp_path, repo_root)
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    with pytest.raises(ESAAError) as exc:
        svc.register_actor(
            actor_id="alias-existing",
            role="qa",
            authorization_scope=["review"],
            actor_public_key_hex=public,
            authorization=auth,
            dry_run=dry_run,
        )
    assert exc.value.code == "ACTOR_DUPLICATE"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    assert svc.show_actor_registry()["aliases"] == {"alias-existing": "agent-spec"}


def test_cli_and_raw_append_enforce_same_namespace(tmp_path, repo_root, capsys):
    svc, _keys, public, auth = _setup(tmp_path, repo_root)
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(auth))
    before = (tmp_path / ".roadmap/activity.jsonl").read_bytes()
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "actor",
                "register",
                "--actor-id",
                "alias-existing",
                "--role",
                "qa",
                "--scope",
                "review",
                "--actor-public-key",
                public,
                "--authorization",
                str(path),
                "--dry-run",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["error_code"] == "ACTOR_DUPLICATE"
    event = make_event(
        next_event_seq(parse_event_store(tmp_path)),
        "orchestrator",
        "actor.register",
        {**auth["payload"]["scope"], "authorization": auth},
    )
    with pytest.raises(ESAAError) as exc:
        append_events(tmp_path, [event])
    assert exc.value.code == "ACTOR_DUPLICATE"
    assert (tmp_path / ".roadmap/activity.jsonl").read_bytes() == before
    assert svc.verify()["verify_status"] == "ok"
