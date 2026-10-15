"""Password hashing (Argon2id) and the password policy."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.kernel import ValidationFailed

_hasher = PasswordHasher()  # Argon2id with the library's current defaults
# Used to spend the same time when the account does not exist (no timing oracle).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

MIN_LENGTH = 10
MAX_LENGTH = 200
_COMMON = {"password123", "1234567890", "qwertyuiop", "letmein123", "password12", "iloveyou12"}


def check_policy(password: str, email: str | None = None) -> None:
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use at most {MAX_LENGTH} characters.")
    if password.isdigit():
        problems.append("Do not use only digits.")
    if password.lower() in _COMMON or (email and password.lower() == email.lower()):
        problems.append("That password is too easy to guess.")
    if problems:
        raise ValidationFailed(" ".join(problems), {"field": "password"})


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older Argon2 parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify in constant-ish time. Pass None when the account does not exist."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False
