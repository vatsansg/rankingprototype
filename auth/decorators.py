"""
@login_required / @role_required(*roles) route decorators. Session stores ONLY app_user_id
(never role, never a cached permission set) -- flask.g.current_user is re-fetched from the
database on every request, so a SUPERADMIN deactivating or re-roling a user takes effect on
that user's very next request, not only after their session/cookie expires.
"""

from __future__ import annotations

from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from auth.models import get_user_by_id
from engine.db import get_connection


def load_logged_in_user() -> None:
    """Registered as a before_request hook in web/app.py."""
    app_user_id = session.get("app_user_id")
    if app_user_id is None:
        g.current_user = None
        return
    conn = get_connection()
    try:
        user = get_user_by_id(conn, app_user_id)
    finally:
        conn.close()
    g.current_user = user if (user is not None and user.is_active) else None
    if g.current_user is None:
        session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user.role_code not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
