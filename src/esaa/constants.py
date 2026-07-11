from __future__ import annotations

SCHEMA_VERSION = "0.4.1"
ESAA_VERSION = "0.4.x"
PACKAGE_VERSION = "0.5.0b17"  # QUA-02: fonte unica de versao; pyproject usa [tool.setuptools.dynamic]

ROADMAP_DIR = ".roadmap"
EVENT_STORE_PATH = ".roadmap/activity.jsonl"
ROADMAP_PATH = ".roadmap/roadmap.json"
ISSUES_PATH = ".roadmap/issues.json"
LESSONS_PATH = ".roadmap/lessons.json"
PROJECT_PROFILE_PATH = ".roadmap/project_profile.json"

ROADMAP_SCHEMA_PATH = ".roadmap/roadmap.schema.json"
PROJECT_PROFILE_SCHEMA_PATH = ".roadmap/project_profile.schema.json"
AGENT_RESULT_SCHEMA_PATH = ".roadmap/agent_result.schema.json"
AGENT_CONTRACT_PATH = ".roadmap/AGENT_CONTRACT.yaml"

CANONICAL_ACTIONS = {
    "run.start",
    "run.end",
    "task.create",
    "task.amend",
    "claim",
    "complete",
    "review",
    "issue.report",
    "hotfix.create",
    "issue.resolve",
    "runner.metrics",
    "project.profile.set",
    "chain.anchor",
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
