"""Request and response models for the identity module."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.kernel import Role


class RegisterRequest(BaseModel):
    organisation_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class CreateMemberRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    role: Role
    password: str = Field(max_length=200)


class ChangeRoleRequest(BaseModel):
    role: Role


class ResetPasswordRequest(BaseModel):
    password: str = Field(max_length=200)


class MeDTO(BaseModel):
    user_id: UUID
    name: str
    email: str
    organisation_id: UUID
    organisation_name: str
    role: Role
    permissions: list[str]


class MemberDTO(BaseModel):
    membership_id: UUID
    user_id: UUID
    name: str
    email: str
    role: Role
    status: str
