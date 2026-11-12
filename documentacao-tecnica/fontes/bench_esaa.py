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
