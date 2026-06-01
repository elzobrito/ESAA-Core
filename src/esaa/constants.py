from __future__ import annotations

SCHEMA_VERSION = "0.4.1"
ESAA_VERSION = "0.4.x"
PACKAGE_VERSION = "0.5.0b1"

ROADMAP_DIR = ".roadmap"
EVENT_STORE_PATH = ".roadmap/activity.jsonl"
ROADMAP_PATH = ".roadmap/roadmap.json"
ISSUES_PATH = ".roadmap/issues.json"
LESSONS_PATH = ".roadmap/lessons.json"

ROADMAP_SCHEMA_PATH = ".roadmap/roadmap.schema.json"
AGENT_RESULT_SCHEMA_PATH = ".roadmap/agent_result.schema.json"
AGENT_CONTRACT_PATH = ".roadmap/AGENT_CONTRACT.yaml"

CANONICAL_ACTIONS = {
    "run.start",
    "run.end",
    "task.create",
    "claim",
    "complete",
    "review",
    "issue.report",
    "hotfix.create",
    "issue.resolve",
    "runner.metrics",
    "output.rejected",
    "orchestrator.file.write",
    "orchestrator.view.mutate",
    "verify.start",
    "verify.ok",
    "verify.fail",
}

RUN_STATUS = {"initialized", "running", "success", "failed", "halted"}
VERIFY_STATUS = {"unknown", "ok", "mismatch", "corrupted"}
TASK_STATUS = {"todo", "in_progress", "review", "done"}
TASK_KINDS = {"spec", "impl", "qa"}
