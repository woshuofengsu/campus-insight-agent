# data/db_user.py
"""User profile CRUD — multi-user support with authentication.

All functions accept an optional user_id parameter. When omitted, they resolve
the current user from:

  1. Explicit override:  set_active_user_id()  (for API / non-UI contexts)
  2. Streamlit session_state._login_user_id    (for UI)

Raises RuntimeError if no user can be resolved.
"""
import json
import logging
from data.db_core import get_db, _hash_password, _verify_password

_log = logging.getLogger(__name__)

# Module-level override for non-Streamlit contexts (e.g., FastAPI)
_explicit_user_id: int | None = None


def set_active_user_id(user_id: int | None) -> None:
    """Set the active user_id for non-Streamlit contexts (e.g., FastAPI).

    Call this at the start of each API request to set the current user.
    Pass None to clear and fall back to Streamlit session_state.
    """
    global _explicit_user_id
    _explicit_user_id = user_id


def _get_active_user_id() -> int:
    """Resolve the active user_id.

    Priority:
      1. Explicit override (set_active_user_id) — for API contexts
      2. Streamlit session_state._login_user_id — for UI

    Raises RuntimeError if no user can be resolved.
    """
    # 1) Explicit override (API / non-UI)
    if _explicit_user_id is not None:
        return _explicit_user_id

    # 2) Streamlit session_state (UI)
    try:
        import streamlit as st
        uid = st.session_state.get("_login_user_id")
        if uid is not None:
            return int(uid)
    except Exception:  # best-effort, skip
        _log.debug("Failed to resolve user from session_state", exc_info=True)
        pass

    raise RuntimeError(
        "No active user session. Call set_active_user_id() from API contexts, "
        "or ensure st.session_state._login_user_id is set in Streamlit."
    )


# ── Authentication ──

def authenticate(username: str, password: str = "") -> dict | None:
    """Verify credentials. Returns user profile dict on success, None on failure.

    Residents (role='resident'): password is optional — empty password accepted.
    Grid managers (role='grid'): password is REQUIRED and verified against hash.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE username = ? AND is_active = 1",
            (username.strip(),),
        ).fetchone()
        if not row:
            return None

        user = dict(row)
        stored_hash = user.get("password_hash", "")

        if user["role"] == "grid":
            # Grid must provide correct password
            if not _verify_password(password, stored_hash):
                return None
        else:
            # Resident: if a password is set, verify it; if not, any/empty password works
            if stored_hash and not _verify_password(password, stored_hash):
                return None

        # Migrate legacy hash format to PBKDF2 on successful login
        if stored_hash and "$" not in stored_hash:
            new_hash = _hash_password(password)
            conn.execute(
                "UPDATE user_profile SET password_hash = ? WHERE id = ?",
                (new_hash, user["id"]),
            )
            conn.commit()
            user["password_hash"] = new_hash

        return user


# ── CRUD ──

def get_current_user() -> dict:
    """Get the currently logged-in user's profile (from session_state).
    Fallback to legacy id=1 for backward compatibility during migration.
    """
    try:
        uid = _get_active_user_id()
        profile = get_user_by_id(uid)
        if profile:
            return profile
        # _get_active_user_id() succeeded but the user was not found in DB
        # (e.g. session_state._login_user_id is stale). Fall through to id=1.
    except RuntimeError:
        pass
    # Legacy fallback: return user id=1 (pre-auth DB)
    return get_user_by_id(1)


def get_user_by_id(user_id: int) -> dict:
    """Get a user profile by ID. Returns empty dict if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            # Fallback to id=1 for legacy compatibility
            if user_id != 1:
                row = conn.execute(
                    "SELECT * FROM user_profile WHERE id = 1"
                ).fetchone()
        return dict(row) if row else {}


def get_user_by_username(username: str) -> dict | None:
    """Get a user profile by username. Returns None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE username = ?", (username.strip(),)
        ).fetchone()
        return dict(row) if row else None


def list_users(role: str | None = None) -> list[dict]:
    """List all active users, optionally filtered by role."""
    with get_db() as conn:
        if role:
            rows = conn.execute(
                "SELECT id, username, role, name, community, resident_id, building, unit "
                "FROM user_profile WHERE is_active = 1 AND role = ? ORDER BY role, id",
                (role,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, username, role, name, community, resident_id, building, unit "
                "FROM user_profile WHERE is_active = 1 ORDER BY role, id"
            ).fetchall()
        return [dict(r) for r in rows]


def create_user(username: str, password: str = "", role: str = "resident",
                community: str = "", building: str = "", unit: str = "",
                name: str = "", resident_id: str = "") -> int:
    """Create a new user. Returns the new user ID. Raises ValueError on duplicate."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM user_profile WHERE username = ?", (username.strip(),)
        ).fetchone()
        if existing:
            raise ValueError(f"Username '{username}' already taken")
        pw_hash = _hash_password(password) if password else ""
        cur = conn.execute(
            """INSERT INTO user_profile
               (username, password_hash, role, community, building, unit, name, resident_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (username.strip(), pw_hash, role, community, building, unit, name, resident_id),
        )
        conn.commit()
        return cur.lastrowid


def update_user_profile(community: str | None = None, building: str | None = None,
                        unit: str | None = None, resident_id: str | None = None,
                        role: str | None = None, name: str | None = None,
                        preferences: list[str] | None = None,
                        user_id: int | None = None,
                        password: str | None = None) -> None:
    """Update user profile fields.

    Pass a string (including empty string) to set; pass None to skip.
    If user_id is None, updates the currently logged-in user.
    Pass password=<new_password> to set/change password; empty string clears it.
    """
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        parts = []
        params: list = []
        if community is not None:
            parts.append("community = ?")
            params.append(community)
        if building is not None:
            parts.append("building = ?")
            params.append(building)
        if resident_id is not None:
            parts.append("resident_id = ?")
            params.append(resident_id)
        if unit is not None:
            parts.append("unit = ?")
            params.append(unit)
        if role is not None:
            parts.append("role = ?")
            params.append(role)
        if name is not None:
            parts.append("name = ?")
            params.append(name)
        if preferences is not None:
            parts.append("preferences = ?")
            params.append(json.dumps(preferences, ensure_ascii=False))
        if password is not None:
            parts.append("password_hash = ?")
            params.append(_hash_password(password) if password else "")
        if parts:
            conn.execute(
                f"UPDATE user_profile SET {', '.join(parts)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                params + [user_id],
            )
            conn.commit()


def set_onboarding_done(user_id: int | None = None) -> None:
    """Mark onboarding as complete for the given user."""
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET onboarding_done = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
        conn.commit()


def reset_onboarding(user_id: int | None = None) -> None:
    """Reset onboarding flag for the given user."""
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET onboarding_done = 0 WHERE id = ?",
            (user_id,),
        )
        conn.commit()


# ── Legacy compatibility wrappers (used by older code that takes no user_id) ──

def get_or_create_user() -> dict:
    """Legacy: get current user profile. Use get_current_user() in new code."""
    return get_current_user()
