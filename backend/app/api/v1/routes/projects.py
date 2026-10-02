from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate,ProjectRead,ProjectUpdate
router=APIRouter(prefix="/projects",tags=["projects"])
def owned(db,id,user_id):
    x=db.scalar(select(Project).where(Project.id==id,Project.user_id==user_id))
    if not x:raise HTTPException(404,"Project not found.")
    return x
@router.post("",response_model=ProjectRead,status_code=status.HTTP_201_CREATED)
def create(payload:ProjectCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=Project(user_id=user.id,**payload.model_dump());db.add(x);db.commit();db.refresh(x);return x
@router.get("",response_model=list[ProjectRead])
def list_all(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return list(db.scalars(select(Project).where(Project.user_id==user.id).order_by(Project.created_at.desc())).all())
@router.patch("/{project_id}",response_model=ProjectRead)
def update(project_id:UUID,payload:ProjectUpdate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,project_id,user.id)
    for k,v in payload.model_dump(exclude_unset=True).items():setattr(x,k,v)
    db.commit();db.refresh(x);return x
@router.delete("/{project_id}",status_code=status.HTTP_204_NO_CONTENT)
def delete(project_id:UUID,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,project_id,user.id);db.delete(x);db.commit()
