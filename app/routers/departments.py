"""
科室管理 API
支持科室的 CRUD、科室主任分配
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import User, Role, Department
from app.schemas import DepartmentInfo, MessageResponse
from app.auth import get_current_user

router = APIRouter()


class DepartmentCreateRequest(BaseModel):
    name: str = Field(..., description="科室名称")
    code: str = Field("", description="科室代码")
    manager_id: Optional[int] = Field(None, description="科室主任 ID")


class DepartmentUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="科室名称")
    code: Optional[str] = Field(None, description="科室代码")
    manager_id: Optional[int] = Field(None, description="科室主任 ID")


@router.get("", response_model=List[DepartmentInfo], tags=["科室管理"])
async def list_departments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有科室列表
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view departments",
        )
    
    departments = db.query(Department).all()
    
    return [DepartmentInfo.from_orm(d) for d in departments]


@router.get("/{dept_id}", response_model=DepartmentInfo, tags=["科室管理"])
async def get_department(
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取科室详情
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can view departments",
        )
    
    department = db.query(Department).filter(Department.id == dept_id).first()
    if not department:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    return DepartmentInfo.from_orm(department)


@router.post("", response_model=DepartmentInfo, tags=["科室管理"])
async def create_department(
    request: DepartmentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建新科室（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can create departments",
        )
    
    # 检查科室名称是否已存在
    existing = db.query(Department).filter(Department.name == request.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department name already exists",
        )
    
    # 如果指定了科室主任，检查用户是否存在
    if request.manager_id:
        manager = db.query(User).filter(User.id == request.manager_id).first()
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Manager user not found",
            )
    
    # 创建新科室
    department = Department(
        name=request.name,
        code=request.code,
        manager_id=request.manager_id,
    )
    
    db.add(department)
    db.commit()
    db.refresh(department)
    
    return DepartmentInfo.from_orm(department)


@router.put("/{dept_id}", response_model=DepartmentInfo, tags=["科室管理"])
async def update_department(
    dept_id: int,
    request: DepartmentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    编辑科室（仅管理员）
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update departments",
        )
    
    department = db.query(Department).filter(Department.id == dept_id).first()
    if not department:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    # 如果修改科室名称，检查是否已存在
    if request.name and request.name != department.name:
        existing = db.query(Department).filter(Department.name == request.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Department name already exists",
            )
    
    # 如果指定了科室主任，检查用户是否存在
    if request.manager_id:
        manager = db.query(User).filter(User.id == request.manager_id).first()
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Manager user not found",
            )
    
    # 更新字段
    if request.name is not None:
        department.name = request.name
    if request.code is not None:
        department.code = request.code
    if request.manager_id is not None:
        department.manager_id = request.manager_id
    
    db.commit()
    db.refresh(department)
    
    return DepartmentInfo.from_orm(department)


@router.delete("/{dept_id}", response_model=MessageResponse, tags=["科室管理"])
async def delete_department(
    dept_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除科室（仅管理员）
    
    注意：删除前需要确保没有用户属于该科室
    """
    # 检查是否为管理员
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can delete departments",
        )
    
    department = db.query(Department).filter(Department.id == dept_id).first()
    if not department:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )
    
    # 检查是否有用户属于该科室
    users_in_dept = db.query(User).filter(User.dept_id == dept_id).count()
    if users_in_dept > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete department with {users_in_dept} users",
        )
    
    # 删除科室
    db.delete(department)
    db.commit()
    
    return MessageResponse(message="Department deleted successfully")
