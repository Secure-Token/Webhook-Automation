from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Execution, Snapshot, Task
from app.schemas.api import (ExecuteRequest, ExecutionOut, SnapshotOut, TaskCreate, TaskOut)
from app.security.authentication import Principal, get_db, get_principal, require_developer
from app.services import execution_service, task_service

router = APIRouter(prefix="/api/v1", tags=["tasks"])


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, p: Principal = Depends(require_developer), db: Session = Depends(get_db)):
    return task_service.create_task(db, p.developer_id, body.description, body.project_id)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(limit: int = 100, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(Task).order_by(Task.created_at.desc()).limit(min(limit, 500))
    if not p.is_admin:
        q = q.where(Task.developer_id == p.developer_id)
    return db.scalars(q).all()


@router.get("/tasks/{task_id}")
def get_task(task_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    task = task_service.get_task_for(db, p, task_id)
    execs = db.scalars(select(Execution).where(Execution.task_id == task.id).order_by(Execution.started_at)).all()
    return {"task": TaskOut.model_validate(task), "executions": [ExecutionOut.model_validate(e) for e in execs]}


@router.post("/tasks/{task_id}/execute", response_model=ExecutionOut, status_code=202)
def execute_task(task_id: str, background: BackgroundTasks, body: ExecuteRequest | None = None,
                 p: Principal = Depends(require_developer), db: Session = Depends(get_db)):
    task = task_service.get_task_for(db, p, task_id)
    ex = execution_service.start_execution(db, task, (body or ExecuteRequest()).model_dump())
    background.add_task(execution_service.run_simulation, ex.id)
    return ex


@router.get("/executions/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ex = db.get(Execution, execution_id)
    if ex is None:
        raise HTTPException(404, "Execution not found")
    task_service.get_task_for(db, p, ex.task_id)  # ownership check
    return ex


@router.get("/tasks/{task_id}/snapshots", response_model=list[SnapshotOut])
def get_snapshots(task_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    task_service.get_task_for(db, p, task_id)
    return db.scalars(select(Snapshot).where(Snapshot.task_id == task_id).order_by(Snapshot.created_at)).all()
