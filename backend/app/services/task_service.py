from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Project, Task
from app.security.authentication import Principal
from app.services import event_service


def default_project(db: Session, developer_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.developer_id == developer_id).order_by(Project.created_at))
    if project is None:
        project = Project(id=new_id("proj"), name="Default Project", developer_id=developer_id)
        db.add(project)
        db.flush()
    return project


def create_task(db: Session, developer_id: str, description: str, project_id: str | None = None) -> Task:
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.developer_id != developer_id:
            raise HTTPException(404, "Project not found")
    else:
        project = default_project(db, developer_id)
    task = Task(id=new_id("task"), project_id=project.id, developer_id=developer_id,
                description=description, status="CREATED")
    db.add(task)
    db.flush()
    event_service.emit(db, "task.created", {"status": task.status, "project_id": project.id},
                       developer_id=developer_id, task_id=task.id)
    db.commit()
    return task


def get_task_for(db: Session, principal: Principal, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or (not principal.is_admin and task.developer_id != principal.developer_id):
        raise HTTPException(404, "Task not found")
    return task
