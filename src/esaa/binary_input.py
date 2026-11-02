"""Prepare non-final, hash-verified binary input for a claimed task."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from .binary_artifacts import store_blob
from .errors import ESAAError
from .task_resource_limits import resolve_task_limits
from .validator import resource_limits_from_policy


def stage_task_input(service: Any, task_id: str, actor: str, source: str, size: int, sha256: str) -> dict[str, Any]:
    """Stage within the workspace. This checks task ownership, not OS identity."""
    root = Path(service.root)
    task = service.task_state(task_id)['task']
    if task.get('status') != 'in_progress' or task.get('assigned_to') != actor:
        raise ESAAError('LOCK_VIOLATION', 'input requires task in progress assigned to actor')
    parts = PurePosixPath(source).parts
    if not parts or parts[0] == '.roadmap' or source.startswith('/') or '\\' in source:
        raise ESAAError('BOUNDARY_VIOLATION', 'binary source must be a relative non-governance workspace path')
    policy = service._policy()
    try:
        limits = resolve_task_limits(resource_limits_from_policy(policy), policy.get('resource_limit_caps'), task.get('resource_limits'))
        max_bytes = min(limits['max_bytes_per_update'], limits['max_bytes_total'])
        if type(size) is not int or size < 0 or size > max_bytes:
            raise ValueError('binary input size exceeds task limit')
    except ValueError as exc:
        raise ESAAError('RESOURCE_LIMIT_INVALID', str(exc)) from exc
    task_key = hashlib.sha256(task_id.encode('utf-8')).hexdigest()
    input_root = root / '.roadmap' / 'binary-input'
    input_root.mkdir(mode=0o700, exist_ok=True)
    if input_root.is_symlink():
        raise ESAAError('BOUNDARY_VIOLATION', 'binary input root is a symlink')
    task_dir = input_root / task_key
    task_dir.mkdir(mode=0o700, exist_ok=True)
    if task_dir.is_symlink():
        raise ESAAError('BOUNDARY_VIOLATION', 'binary task input is a symlink')
    try:
        store_blob(root, source, task_dir, size=size, sha256=sha256, limit=max_bytes)
    except (ValueError, OSError) as exc:
        raise ESAAError('INPUT_INVALID', f'binary input verification failed: {exc}') from exc
    return {'status': 'staged', 'task_id': task_id, 'binary': {'source': sha256, 'size': size, 'sha256': sha256}, 'note': 'temporary input; no final file effect'}
