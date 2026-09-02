"""
User/role data access + audit logging for the RBAC subsystem (dbo.app_user, dbo.app_role,
dbo.app_user_audit_log -- see db/schema_mssql.sql). "Delete" a user is always deactivation
(is_active=0), never a hard DELETE, to preserve referential integrity for historical
triggered_by/modified_by/audit references -- consistent with the app's "never truly wipe
history" pattern elsewhere. The last active SUPERADMIN can never be deactivated.
"""

from __future__ import annotations

import pyodbc
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("SUPERADMIN", "RANKINGUSER", "RANKINGVIEWER")


class LastSuperadminError(Exception):
    """Raised when an action would leave zero active SUPERADMIN users."""


def _log(conn: pyodbc.Connection, *, action_type: str, target_app_user_id: int | None,
         performed_by: str, details: str | None = None) -> None:
    conn.cursor().execute(
        "INSERT INTO dbo.app_user_audit_log (action_type, target_app_user_id, performed_by, details) "
        "VALUES (?, ?, ?, ?)",
        action_type, target_app_user_id, performed_by, details,
    )


def get_user_by_id(conn: pyodbc.Connection, app_user_id: int) -> pyodbc.Row | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM dbo.app_user WHERE app_user_id = ?", app_user_id)
    return cur.fetchone()


def get_user_by_username(conn: pyodbc.Connection, username: str) -> pyodbc.Row | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM dbo.app_user WHERE username = ?", username)
    return cur.fetchone()


def list_users(conn: pyodbc.Connection) -> list[pyodbc.Row]:
    cur = conn.cursor()
    cur.execute(
        "SELECT app_user_id, username, role_code, is_active, created_at, updated_at, last_login_at, created_by "
        "FROM dbo.app_user ORDER BY username"
    )
    return cur.fetchall()


def count_active_superadmins(conn: pyodbc.Connection, *, excluding_app_user_id: int | None = None) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM dbo.app_user WHERE role_code = 'SUPERADMIN' AND is_active = 1 "
        "AND (? IS NULL OR app_user_id <> ?)",
        excluding_app_user_id, excluding_app_user_id,
    )
    return cur.fetchone()[0]


def verify_login(conn: pyodbc.Connection, username: str, password: str) -> pyodbc.Row | None:
    """Returns the user row on success (after recording LOGIN_SUCCESS and last_login_at), or
    None on bad credentials / inactive account (after recording LOGIN_FAILURE)."""
    user = get_user_by_username(conn, username)
    if user is None or not user.is_active or not check_password_hash(user.password_hash, password):
        _log(conn, action_type="LOGIN_FAILURE", target_app_user_id=user.app_user_id if user else None,
             performed_by=username)
        return None

    conn.cursor().execute(
        "UPDATE dbo.app_user SET last_login_at = SYSUTCDATETIME() WHERE app_user_id = ?", user.app_user_id
    )
    _log(conn, action_type="LOGIN_SUCCESS", target_app_user_id=user.app_user_id, performed_by=username)
    return user


def create_user(conn: pyodbc.Connection, *, username: str, password: str, role_code: str, created_by: str) -> int:
    if role_code not in ROLES:
        raise ValueError(f"role_code must be one of {ROLES}, got {role_code!r}")
    password_hash = generate_password_hash(password)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dbo.app_user (username, password_hash, role_code, created_by) OUTPUT INSERTED.app_user_id "
        "VALUES (?, ?, ?, ?)",
        username, password_hash, role_code, created_by,
    )
    new_id = cur.fetchone()[0]
    _log(conn, action_type="CREATE_USER", target_app_user_id=new_id, performed_by=created_by,
         details=f"username={username}, role={role_code}")
    return new_id


def update_user_role(conn: pyodbc.Connection, *, app_user_id: int, role_code: str, performed_by: str) -> None:
    if role_code not in ROLES:
        raise ValueError(f"role_code must be one of {ROLES}, got {role_code!r}")
    user = get_user_by_id(conn, app_user_id)
    if user is None:
        raise ValueError(f"app_user {app_user_id} not found")
    if user.role_code == "SUPERADMIN" and role_code != "SUPERADMIN" and count_active_superadmins(conn, excluding_app_user_id=app_user_id) == 0:
        raise LastSuperadminError("Cannot change the role of the last active SUPERADMIN.")

    conn.cursor().execute(
        "UPDATE dbo.app_user SET role_code = ?, updated_at = SYSUTCDATETIME() WHERE app_user_id = ?",
        role_code, app_user_id,
    )
    _log(conn, action_type="ROLE_CHANGE", target_app_user_id=app_user_id, performed_by=performed_by,
         details=f"{user.role_code} -> {role_code}")


def set_active(conn: pyodbc.Connection, *, app_user_id: int, is_active: bool, performed_by: str) -> None:
    user = get_user_by_id(conn, app_user_id)
    if user is None:
        raise ValueError(f"app_user {app_user_id} not found")
    if not is_active and user.role_code == "SUPERADMIN" and count_active_superadmins(conn, excluding_app_user_id=app_user_id) == 0:
        raise LastSuperadminError("Cannot deactivate the last active SUPERADMIN.")

    conn.cursor().execute(
        "UPDATE dbo.app_user SET is_active = ?, updated_at = SYSUTCDATETIME() WHERE app_user_id = ?",
        1 if is_active else 0, app_user_id,
    )
    _log(conn, action_type="ACTIVATE_USER" if is_active else "DEACTIVATE_USER",
         target_app_user_id=app_user_id, performed_by=performed_by)


def reset_password(conn: pyodbc.Connection, *, app_user_id: int, new_password: str, performed_by: str) -> None:
    """Admin-initiated password reset (SUPERADMIN resetting someone else's password)."""
    password_hash = generate_password_hash(new_password)
    conn.cursor().execute(
        "UPDATE dbo.app_user SET password_hash = ?, updated_at = SYSUTCDATETIME() WHERE app_user_id = ?",
        password_hash, app_user_id,
    )
    _log(conn, action_type="RESET_PASSWORD", target_app_user_id=app_user_id, performed_by=performed_by)


def change_own_password(conn: pyodbc.Connection, *, app_user_id: int, current_password: str, new_password: str) -> str | None:
    """Self-service password change. Returns an error message string on failure, else None."""
    user = get_user_by_id(conn, app_user_id)
    if user is None or not check_password_hash(user.password_hash, current_password):
        return "Current password is incorrect."

    password_hash = generate_password_hash(new_password)
    conn.cursor().execute(
        "UPDATE dbo.app_user SET password_hash = ?, updated_at = SYSUTCDATETIME() WHERE app_user_id = ?",
        password_hash, app_user_id,
    )
    _log(conn, action_type="SELF_PASSWORD_CHANGE", target_app_user_id=app_user_id, performed_by=user.username)
    return None
