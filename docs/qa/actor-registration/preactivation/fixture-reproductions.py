import json
import runpy
from pathlib import Path

import pytest

from esaa.service import ESAAService
from esaa.store import parse_event_store

REPO = Path('/home/elzobrito/desenvolvimento/ESAA-Core')
helpers = runpy.run_path(str(REPO / 'tests/test_actor_registration.py'))

def activated(tmp_path):
    return helpers['_activated'](tmp_path, REPO)

def replace_fixture_events(root, events):
    # Deliberate attacker edits restricted to disposable pytest workspace.
    (root / '.roadmap/activity.jsonl').write_text(
        ''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')

def test_replay_verify_accept_invalid_identity_signatures(tmp_path):
    svc, keys = activated(tmp_path)
    helpers['_ready_task'](svc)
    auth = helpers['_review_auth'](keys['reviewer'], keys['project_id'], '21'*16,
                                    'reviewer-qa', 'T-1000', 'approve')
    svc.review_task('T-1000', actor='reviewer-qa', decision='approve', authorization=auth)
    events = parse_event_store(tmp_path)
    changed = []
    for e in events:
        blob = e['payload'].get('authorization') or e['payload'].get('_authorization')
        if blob:
            blob['signature_hex'] = '00'*64
            changed.append(e['action'])
    replace_fixture_events(tmp_path, events)
    assert svc.verify()['verify_status'] == 'ok'
    assert svc.replay(write_views=False)['verify_status'] == 'ok'
    print('INVALID_SIGNATURES_ACCEPTED', changed)

def test_replace_anchor_and_bootstrap_payload_then_register(tmp_path):
    svc, keys = activated(tmp_path)
    attacker, attacker_pub = helpers['_key']()
    anchor = helpers['_write_anchor'](tmp_path, attacker_pub)
    events = parse_event_store(tmp_path)
    for e in events:
        if e['action'] == 'actor.bootstrap':
            e['payload']['public_key_hex'] = attacker_pub
            e['payload']['fingerprint_sha256'] = anchor['fingerprint_sha256']
    replace_fixture_events(tmp_path, events)
    qa, qa_pub = helpers['_key']()
    result = svc.register_actor(actor_id='attacker-qa', role='qa',
        authorization_scope=['review'], actor_public_key_hex=qa_pub,
        authorization=helpers['_register_auth'](attacker, anchor['fingerprint_sha256'],
                                               '22'*16, 'attacker-qa', 'qa', qa_pub))
    assert result['status'] == 'accepted'
    assert svc.verify()['verify_status'] == 'ok'
    print('REPLACEMENT_ANCHOR_ACCEPTED')

def test_identity_rollback_enters_unsigned_qa_role_path(tmp_path):
    svc, keys = activated(tmp_path)
    helpers['_ready_task'](svc)
    events = [e for e in parse_event_store(tmp_path)
              if e['action'] not in {'actor.bootstrap', 'actor.register'}]
    for seq, e in enumerate(events, 1):
        e['event_seq'] = seq
        e['event_id'] = f'EV-{seq:08d}'
    replace_fixture_events(tmp_path, events)
    result = svc.review_task('T-1000', actor='agent-qa', decision='approve')
    assert result['status'] == 'accepted'
    assert result['task']['status'] == 'done'
    print('UNSIGNED_QA_FALLBACK_ACCEPTED_AFTER_ROLLBACK')

def test_reviewer_claims_under_unsigned_alias_and_self_approves(tmp_path):
    svc, keys = activated(tmp_path)
    helpers['_ready_task'](svc, actor='reviewer-alias')
    auth = helpers['_review_auth'](keys['reviewer'], keys['project_id'], '23'*16,
                                    'reviewer-qa', 'T-1000', 'approve')
    result = svc.review_task('T-1000', actor='reviewer-qa', decision='approve', authorization=auth)
    assert result['status'] == 'accepted'
    assert result['task']['status'] == 'done'
    print('CLAIM_COMPLETE_UNSIGNED_ALIAS_ACCEPTED_AND_APPROVED')
