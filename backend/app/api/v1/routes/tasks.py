from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.target import Target
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate,TaskRead,TaskUpdate
router=APIRouter(prefix="/tasks",tags=["tasks"])
def owned(db,model,id,user_id):
    x=db.scalar(select(model).where(model.id==id,model.user_id==user_id))
    if not x:raise HTTPException(404,f"{model.__name__} not found.")
    return x
def validate_links(db,payload,user_id):
    if payload.project_id is not None: owned(db,Project,payload.project_id,user_id)
    if payload.target_id is not None: owned(db,Target,payload.target_id,user_id)
@router.post("",response_model=TaskRead,status_code=status.HTTP_201_CREATED)
def create(payload:TaskCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    validate_links(db,payload,user.id);x=Task(user_id=user.id,**payload.model_dump());db.add(x);db.commit();db.refresh(x);return x
@router.get("",response_model=list[TaskRead])
def list_all(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return list(db.scalars(select(Task).where(Task.user_id==user.id).order_by(Task.due_at.nulls_last(),Task.priority)).all())
@router.patch("/{task_id}",response_model=TaskRead)
def update(task_id:UUID,payload:TaskUpdate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,Task,task_id,user.id);validate_links(db,payload,user.id)
    for k,v in payload.model_dump(exclude_unset=True).items():setattr(x,k,v)
    db.commit();db.refresh(x);return x
@router.delete("/{task_id}",status_code=status.HTTP_204_NO_CONTENT)
def delete(task_id:UUID,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,Task,task_id,user.id);db.delete(x);db.commit()
