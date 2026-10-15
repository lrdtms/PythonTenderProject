"""Public surface of the identity module. Other layers import only from here."""

from .schemas import (
    ChangeRoleRequest,
    CreateMemberRequest,
    LoginRequest,
    MeDTO,
    MemberDTO,
    RegisterRequest,
    ResetPasswordRequest,
)
from .service import (
    change_role,
    create_member,
    list_members,
    login,
    logout,
    me,
    register_organisation,
    reset_member_password,
    resolve_context,
    set_member_status,
)

__all__ = [
    "ChangeRoleRequest",
    "CreateMemberRequest",
    "LoginRequest",
    "MeDTO",
    "MemberDTO",
    "RegisterRequest",
    "ResetPasswordRequest",
    "change_role",
    "create_member",
    "list_members",
    "login",
    "logout",
    "me",
    "register_organisation",
    "reset_member_password",
    "resolve_context",
    "set_member_status",
]
