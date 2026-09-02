"""
One-time seed for the initial SUPERADMIN account. Safe to commit: the plaintext password
never appears in any persisted artifact -- only its PBKDF2 hash (via werkzeug) is written to
the database. The literal default below exists only as a documented starting point (per the
approved migration plan); operators must change it via /account/password immediately after
first login.

Usage: python db/seed_app_users.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from werkzeug.security import generate_password_hash  # noqa: E402

from engine.db import get_connection  # noqa: E402

ADMIN_USERNAME = os.environ.get("ADMIN_SEED_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD") or "Admin@123"


def seed() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM dbo.app_user WHERE username = ?", ADMIN_USERNAME)
        if cur.fetchone():
            print(f"{ADMIN_USERNAME!r} already exists, skipping.")
            return
        password_hash = generate_password_hash(ADMIN_PASSWORD)
        cur.execute(
            "INSERT INTO dbo.app_user (username, password_hash, role_code, is_active, created_by) "
            "VALUES (?, ?, 'SUPERADMIN', 1, 'seed_script')",
            ADMIN_USERNAME, password_hash,
        )
        print(f"Seeded SUPERADMIN user {ADMIN_USERNAME!r}.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
