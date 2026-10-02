from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.habit import Habit
from app.models.user import User
from app.schemas.habit import HabitCreate, HabitRead, HabitUpdate
router = APIRouter(prefix="/habits", tags=["habits"])
def owned(db, habit_id, user_id):
    habit=db.scalar(select(Habit).where(Habit.id==habit_id,Habit.user_id==user_id))
    if not habit: raise HTTPException(404,"Habit not found.")
    return habit
@router.post("",response_model=HabitRead,status_code=status.HTTP_201_CREATED)
def create(payload:HabitCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=Habit(user_id=user.id,**payload.model_dump());db.add(x);db.commit();db.refresh(x);return x
@router.get("",response_model=list[HabitRead])
def list_all(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return list(db.scalars(select(Habit).where(Habit.user_id==user.id).order_by(Habit.active.desc(),Habit.name)).all())
@router.patch("/{habit_id}",response_model=HabitRead)
def update(habit_id:UUID,payload:HabitUpdate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,habit_id,user.id)
    for k,v in payload.model_dump(exclude_unset=True).items():setattr(x,k,v)
    db.commit();db.refresh(x);return x
@router.delete("/{habit_id}",status_code=status.HTTP_204_NO_CONTENT)
def delete(habit_id:UUID,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    x=owned(db,habit_id,user.id);db.delete(x);db.commit()
