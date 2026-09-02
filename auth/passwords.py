"""Password policy shared by admin-set and self-service password changes: length >= 8, at
least one digit, at least one letter."""

from __future__ import annotations

import re


def validate_password(password: str) -> str | None:
    """Returns an error message string if the password is invalid, else None."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return "Password must contain at least one letter."
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one digit."
    return None
