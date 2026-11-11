from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .binary_payload import stage_binary


def dry_run_binary(root: Path, item: dict[str, Any], task_id: str | None) -> dict[str, Any]:
    if not task_id:
        raise ValueError("binary update requires task identity")
    from .file_effects import assert_confined_destination

    # AUD-O0-050: o dry-run aplica a mesma validacao de destino do caminho real.
    assert_confined_destination(
        root, item["path"], item.get("_esaa_final_abs_path"), item.get("_esaa_target_root")
    )
    binary = item["binary"]
    task_key = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        stage_binary(
            root / ".roadmap" / "binary-input" / task_key,
            binary["source"],
            Path(tmp),
            size=binary["size"],
            sha256=binary["sha256"],
            limit=binary["size"],
        )
    return {
        "path": item["path"],
        "after_sha256": binary["sha256"],
        "bytes": binary["size"],
        "encoding": "binary",
        "artifact_sha256": None,
        "artifact_path": None,
    }
