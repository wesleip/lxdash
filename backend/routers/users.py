from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from dependencies import CurrentUser, DBDep
from models.user import User, UserRole
from schemas.user import UserCreate, UserResponse, UserUpdate
from services.auth_service import hash_password

router = APIRouter(prefix="/users", tags=["users"])
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Guard: admin-only
# ---------------------------------------------------------------------------

def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return current_user


AdminUser = Depends(require_admin)


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------

@router.get("", response_model=list[UserResponse], summary="List all users")
async def list_users(
    db: DBDep,
    _: User = AdminUser,
) -> list[User]:
    return db.query(User).order_by(User.id).all()


# ---------------------------------------------------------------------------
# POST /users
# ---------------------------------------------------------------------------

@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Create user")
async def create_user(
    body: UserCreate,
    db: DBDep,
    _: User = AdminUser,
) -> User:
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken.",
        )
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered.",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user.created", username=user.username, role=user.role)
    return user


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}
# ---------------------------------------------------------------------------

@router.patch("/{user_id}", response_model=UserResponse, summary="Update user")
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: DBDep,
    current_user: User = AdminUser,
) -> User:
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if body.email is not None:
        conflict = db.query(User).filter(User.email == body.email, User.id != user_id).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{body.email}' is already registered.",
            )
        user.email = body.email

    if body.role is not None:
        if user.id == current_user.id and body.role != UserRole.admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove your own admin role.",
            )
        user.role = body.role

    if body.is_active is not None:
        if user.id == current_user.id and not body.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account.",
            )
        user.is_active = body.is_active

    db.commit()
    db.refresh(user)
    logger.info("user.updated", user_id=user.id)
    return user


# ---------------------------------------------------------------------------
# POST /users/{user_id}/reset-password
# ---------------------------------------------------------------------------

class PasswordResetRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Reset user password")
async def reset_password(
    user_id: int,
    body: PasswordResetRequest,
    db: DBDep,
    _: User = AdminUser,
) -> Response:
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    user.hashed_password = hash_password(body.password)
    db.commit()
    logger.info("user.password_reset", user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}
# ---------------------------------------------------------------------------

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Delete user")
async def delete_user(
    user_id: int,
    db: DBDep,
    current_user: User = AdminUser,
) -> Response:
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account.",
        )
    user: User | None = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    db.delete(user)
    db.commit()
    logger.info("user.deleted", user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
