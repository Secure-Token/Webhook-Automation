"""Snapshot & evidence service.

MOCK ONLY: snapshots are stored JSON records with fabricated project state and diff data.
They are not equivalent to a Git-based snapshot system.
"""
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Execution, Snapshot, Task
from app.services import event_service

BASELINE_TESTS = {"passed": 40, "failed": 0}


def capture_baseline(db: Session, task: Task, execution: Execution) -> Snapshot:
    snap = Snapshot(
        id=new_id("snap"), task_id=task.id, execution_id=execution.id, snapshot_type="BASELINE",
        project_state={"mock": True, "revision": f"mock-rev-{task.id[-6:]}-base", "files": 128,
                       "tests": dict(BASELINE_TESTS)},
        change_summary={"mock": True, "files_changed": 0},
        evidence_ref=f"evidence://{task.id}/{execution.id}/baseline",
    )
    db.add(snap)
    db.flush()
    event_service.emit(db, "snapshot.baseline.created",
                       {"snapshot_id": snap.id, "snapshot_type": "BASELINE", "evidence_ref": snap.evidence_ref},
                       developer_id=task.developer_id, task_id=task.id, execution_id=execution.id)
    return snap


def capture_post_change(db: Session, task: Task, execution: Execution) -> Snapshot:
    opts = execution.options or {}
    failed = execution.status == "FAILED"
    regression = bool(opts.get("simulate_regression")) and not failed
    if failed:  # failed run leaves the project unchanged
        tests = dict(BASELINE_TESTS)
        summary = {"mock": True, "files_changed": 0, "lines_added": 0, "lines_removed": 0}
    elif regression:
        tests = {"passed": 37, "failed": 3}
        summary = {"mock": True, "files_changed": 4, "lines_added": 96, "lines_removed": 12,
                   "note": "mock regression: 3 previously passing tests now fail"}
    else:
        tests = {"passed": 44, "failed": 0}
        summary = {"mock": True, "files_changed": 3, "lines_added": 74, "lines_removed": 9}
    snap = Snapshot(
        id=new_id("snap"), task_id=task.id, execution_id=execution.id, snapshot_type="POST_CHANGE",
        project_state={"mock": True, "revision": f"mock-rev-{task.id[-6:]}-post", "files": 128 + summary["files_changed"],
                       "tests": tests},
        change_summary=summary,
        evidence_ref=f"evidence://{task.id}/{execution.id}/post-change",
    )
    db.add(snap)
    db.flush()
    event_service.emit(db, "snapshot.post.created",
                       {"snapshot_id": snap.id, "snapshot_type": "POST_CHANGE", "evidence_ref": snap.evidence_ref},
                       developer_id=task.developer_id, task_id=task.id, execution_id=execution.id)
    return snap
