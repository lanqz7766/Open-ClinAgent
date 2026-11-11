from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request, Response

from clinagent.platform.local_data import REPO_ROOT

SESSION_COOKIE_NAME = os.getenv("CLINAGENT_AUTH_COOKIE_NAME", "clinagent_session").strip() or "clinagent_session"
DUA_VERSION = "clinagent-dua-v1"
AUTH_SCHEMA_VERSION = 4
ACTIVE_JOB_STATUSES = ("queued", "running")
TERMINAL_JOB_STATUSES = ("completed", "completed_with_errors", "failed")


class RateLimitExceeded(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


@dataclass(frozen=True)
class AuthSession:
    token: str
    expires_at: datetime


class ClinAgentAuthStore:
    def __init__(
        self,
        db_path: Path,
        *,
        require_user_auth: bool = False,
        allow_self_registration: bool = True,
        session_days: int = 7,
        session_idle_hours: int = 12,
        cookie_secure: bool = False,
        allow_local_password_reset: bool = False,
    ) -> None:
        self.db_path = db_path
        self.require_user_auth = require_user_auth
        self.allow_self_registration = allow_self_registration
        self.session_days = session_days
        self.session_idle_hours = session_idle_hours
        self.cookie_secure = cookie_secure
        self.allow_local_password_reset = allow_local_password_reset
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> "ClinAgentAuthStore":
        configured_path = os.getenv("CLINAGENT_AUTH_DB", "").strip()
        db_path = Path(configured_path).expanduser() if configured_path else REPO_ROOT / ".clinagent" / "auth" / "auth.sqlite3"
        return cls(
            db_path.resolve(),
            require_user_auth=_env_flag("CLINAGENT_REQUIRE_USER_AUTH", default=False),
            allow_self_registration=_env_flag("CLINAGENT_ALLOW_SELF_REGISTRATION", default=False),
            session_days=int(os.getenv("CLINAGENT_AUTH_SESSION_DAYS", "7")),
            session_idle_hours=int(os.getenv("CLINAGENT_AUTH_SESSION_IDLE_HOURS", "12")),
            cookie_secure=_env_flag("CLINAGENT_AUTH_COOKIE_SECURE", default=False),
            allow_local_password_reset=_env_flag("CLINAGENT_AUTH_ALLOW_LOCAL_PASSWORD_RESET", default=False),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    organization TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'radiologist',
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    email_verified_at TEXT,
                    dua_version TEXT NOT NULL,
                    dua_accepted_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    revoked_at TEXT,
                    ip_address TEXT,
                    user_agent TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT
                );

                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    ip_address TEXT,
                    user_agent TEXT
                );

                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    organization TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'radiologist',
                    token_hash TEXT NOT NULL UNIQUE,
                    created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS owned_cases (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    shared INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS case_assets (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES owned_cases(id) ON DELETE CASCADE,
                    asset_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(case_id, asset_key)
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    case_id TEXT REFERENCES owned_cases(id) ON DELETE CASCADE,
                    job_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    case_id TEXT REFERENCES owned_cases(id) ON DELETE SET NULL,
                    category TEXT NOT NULL,
                    workflow_step TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_rate_events (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    key_value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_token_active
                    ON sessions(token_hash, revoked_at, expires_at);
                CREATE INDEX IF NOT EXISTS idx_invitations_email
                    ON invitations(email, expires_at);
                CREATE INDEX IF NOT EXISTS idx_owned_cases_owner
                    ON owned_cases(owner_user_id, shared, deleted_at);
                CREATE INDEX IF NOT EXISTS idx_jobs_owner
                    ON jobs(owner_user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_auth_rate_events
                    ON auth_rate_events(scope, key_value, created_at);
                """
            )
            self._ensure_column(conn, "users", "email_verified_at", "TEXT")
            self._ensure_column(conn, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sessions", "last_seen_at", "TEXT")
            self._ensure_column(conn, "jobs", "status", "TEXT NOT NULL DEFAULT 'external'")
            self._ensure_column(conn, "jobs", "stage", "TEXT NOT NULL DEFAULT 'external'")
            self._ensure_column(conn, "jobs", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "jobs", "result_json", "TEXT")
            self._ensure_column(conn, "jobs", "error_message", "TEXT")
            self._ensure_column(conn, "jobs", "started_at", "TEXT")
            self._ensure_column(conn, "jobs", "updated_at", "TEXT")
            self._ensure_column(conn, "jobs", "completed_at", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, job_type, created_at)")
            # Backfill only legacy accounts, never mark operator-created logins as email-verified.
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version = 4").fetchone():
                conn.execute(
                    "UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL AND status = 'active'"
                )
            conn.execute(
                "UPDATE sessions SET last_seen_at = created_at WHERE last_seen_at IS NULL"
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (AUTH_SCHEMA_VERSION, _iso_now()),
            )

    def config(self) -> dict[str, Any]:
        return {
            "auth_required": self.require_user_auth,
            "allow_self_registration": self.allow_self_registration,
            "allow_local_password_reset": self.allow_local_password_reset,
            "dua_version": DUA_VERSION,
            "session_days": self.session_days,
            "session_idle_hours": self.session_idle_hours,
            "invitation_only": not self.allow_self_registration,
        }

    @property
    def schema_version(self) -> int:
        return AUTH_SCHEMA_VERSION

    def _password_hash(self, password: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 390_000)
        return derived.hex(), salt.hex()

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters.")
        if len(password) > 128:
            raise ValueError("Password must be no more than 128 characters.")

    def create_user(
        self,
        *,
        email: str,
        password: str,
        name: str,
        organization: str,
        role: str,
        dua_accepted: bool,
    ) -> dict[str, Any]:
        email = _normalize_email(email)
        name = name.strip()
        organization = organization.strip()
        role = role.strip() or "radiologist"
        if not self.allow_self_registration:
            raise ValueError("Self-registration is disabled for this ClinAgent deployment.")
        if role not in {"radiologist", "resident", "researcher"}:
            raise ValueError("This role requires an administrator invitation.")
        if not email or "@" not in email:
            raise ValueError("A valid email is required.")
        self._validate_password(password)
        if not name:
            raise ValueError("Name is required.")
        if not dua_accepted:
            raise ValueError("DUA acceptance is required before using clinical data workflows.")

        password_hash, password_salt = self._password_hash(password)
        now = _iso_now()
        user_id = str(uuid.uuid4())
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, email, name, organization, role, password_hash, password_salt,
                        email_verified_at, dua_version, dua_accepted_at, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        name,
                        organization,
                        role,
                        password_hash,
                        password_salt,
                        now,
                        DUA_VERSION,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account already exists for this email.") from exc
        return self.get_user(user_id) or {}

    def create_invitation(
        self,
        *,
        email: str,
        name: str,
        organization: str,
        role: str,
        created_by_user_id: str | None = None,
        expires_hours: int = 72,
    ) -> tuple[dict[str, Any], str]:
        email = _normalize_email(email)
        name = name.strip()
        organization = organization.strip()
        role = role.strip() or "radiologist"
        if not email or "@" not in email:
            raise ValueError("A valid email is required.")
        if not name:
            raise ValueError("Name is required.")
        if role not in {"radiologist", "resident", "researcher", "admin"}:
            raise ValueError("Unsupported clinical role.")
        token = secrets.token_urlsafe(40)
        now = _utc_now()
        invitation_id = str(uuid.uuid4())
        with self._connect() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing is not None:
                raise ValueError("An account already exists for this email.")
            conn.execute(
                "UPDATE invitations SET revoked_at = ? WHERE email = ? AND accepted_at IS NULL AND revoked_at IS NULL",
                (now.isoformat(), email),
            )
            conn.execute(
                """
                INSERT INTO invitations (
                    id, email, name, organization, role, token_hash, created_by_user_id, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invitation_id,
                    email,
                    name,
                    organization,
                    role,
                    _hash_token(token),
                    created_by_user_id,
                    now.isoformat(),
                    (now + timedelta(hours=max(1, expires_hours))).isoformat(),
                ),
            )
        return self.invitation_from_token(token), token

    def invitation_from_token(self, token: str) -> dict[str, Any]:
        now = _iso_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, email, name, organization, role, created_at, expires_at
                FROM invitations
                WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
                """,
                (_hash_token(token), now),
            ).fetchone()
        if row is None:
            raise ValueError("Invitation is invalid or expired.")
        return dict(row)

    def accept_invitation(self, *, token: str, password: str, dua_accepted: bool) -> dict[str, Any]:
        self._validate_password(password)
        if not dua_accepted:
            raise ValueError("DUA acceptance is required before using clinical data workflows.")
        now = _iso_now()
        password_hash, password_salt = self._password_hash(password)
        user_id = str(uuid.uuid4())
        try:
            with self._connect() as conn:
                invitation = conn.execute(
                    """
                    SELECT * FROM invitations
                    WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
                    """,
                    (_hash_token(token), now),
                ).fetchone()
                if invitation is None:
                    raise ValueError("Invitation is invalid or expired.")
                conn.execute(
                    """
                    INSERT INTO users (
                        id, email, name, organization, role, password_hash, password_salt, status,
                        email_verified_at, dua_version, dua_accepted_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        invitation["email"],
                        invitation["name"],
                        invitation["organization"],
                        invitation["role"],
                        password_hash,
                        password_salt,
                        now,
                        DUA_VERSION,
                        now,
                        now,
                    ),
                )
                changed = conn.execute(
                    "UPDATE invitations SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL",
                    (now, invitation["id"]),
                ).rowcount
                if changed != 1:
                    raise ValueError("Invitation is invalid or expired.")
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account already exists for this email.") from exc
        return self.get_user(user_id) or {}

    def verify_user(self, email: str, password: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (_normalize_email(email),)).fetchone()
            if row is None or row["status"] != "active":
                return None
            expected, _ = self._password_hash(password, row["password_salt"])
            if not hmac.compare_digest(expected, row["password_hash"]):
                return None
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso_now(), row["id"]))
            updated = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return self._public_user(updated)

    def provision_user(self, *, email: str, password: str, name: str,
                       organization: str = "", role: str = "radiologist") -> dict[str, Any]:
        """Operator-only provisioning; recipients must set their own password and consent."""
        email = _normalize_email(email)
        if not email or "@" not in email or not name.strip():
            raise ValueError("Name and email are required.")
        if role not in {"radiologist", "resident", "researcher", "admin"}:
            raise ValueError("Unsupported account role.")
        self._validate_password(password)
        password_hash, salt = self._password_hash(password)
        user_id = str(uuid.uuid4())
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO users (id, email, name, organization, role, password_hash,
                       password_salt, dua_version, dua_accepted_at, created_at, must_change_password)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, 1)""",
                    (user_id, email, name.strip(), organization.strip(), role, password_hash, salt, _iso_now()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account already exists for this email.") from exc
        return self.get_user(user_id) or {}

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [self._public_user(row) for row in conn.execute("SELECT * FROM users ORDER BY created_at DESC, id")]

    @staticmethod
    def _revoke_credentials(conn: sqlite3.Connection, user_id: str) -> None:
        now = _iso_now()
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
        conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (now, user_id))

    def set_user_status(self, user_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "suspended"}:
            raise ValueError("Status must be active or suspended.")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise LookupError("Account not found.")
            if row["role"] == "admin":
                raise ValueError("Administrator accounts cannot be suspended here.")
            conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
            if status == "suspended":
                self._revoke_credentials(conn, user_id)
        return self.get_user(user_id) or {}

    def set_temporary_password(self, user_id: str, password: str) -> dict[str, Any]:
        self._validate_password(password)
        password_hash, salt = self._password_hash(password)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise LookupError("Account not found.")
            conn.execute("UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 1 WHERE id = ?",
                         (password_hash, salt, user_id))
            self._revoke_credentials(conn, user_id)
        return self.get_user(user_id) or {}

    def complete_account_setup(self, *, user_id: str, current_password: str,
                               new_password: str, dua_accepted: bool) -> dict[str, Any]:
        self._validate_password(new_password)
        if new_password == current_password:
            raise ValueError("Choose a password different from the initial password.")
        password_hash, salt = self._password_hash(new_password)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None or row["status"] != "active":
                raise ValueError("Account is not active.")
            expected, _ = self._password_hash(current_password, row["password_salt"])
            if not hmac.compare_digest(expected, row["password_hash"]):
                raise ValueError("Current password is incorrect.")
            if not row["dua_accepted_at"] and not dua_accepted:
                raise ValueError("Confirm the research-use agreement to continue.")
            conn.execute(
                """UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 0,
                   dua_version = ?, dua_accepted_at = ? WHERE id = ?""",
                (password_hash, salt, row["dua_version"] or DUA_VERSION,
                 row["dua_accepted_at"] or _iso_now(), user_id),
            )
            self._revoke_credentials(conn, user_id)
        return self.get_user(user_id) or {}

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        self._validate_password(new_password)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None or row["status"] != "active":
                raise ValueError("Account is not active.")
            expected, _ = self._password_hash(current_password, row["password_salt"])
            if not hmac.compare_digest(expected, row["password_hash"]):
                raise ValueError("Current password is incorrect.")
            password_hash, password_salt = self._password_hash(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (password_hash, password_salt, user_id),
            )
            self._revoke_credentials(conn, user_id)

    def create_password_reset_token(self, email: str, request: Request) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? AND status = 'active'",
                (_normalize_email(email),),
            ).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(40)
            expires_at = _utc_now() + timedelta(minutes=30)
            conn.execute(
                """
                INSERT INTO password_reset_tokens (
                    id, user_id, token_hash, created_at, expires_at, ip_address, user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    row["id"],
                    _hash_token(token),
                    _iso_now(),
                    expires_at.isoformat(),
                    _safe_ip(request),
                    request.headers.get("user-agent", "")[:300],
                ),
            )
            return token

    def reset_password_with_token(self, token: str, new_password: str) -> dict[str, Any]:
        self._validate_password(new_password)
        now = _iso_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT password_reset_tokens.*, users.status AS user_status
                FROM password_reset_tokens
                JOIN users ON users.id = password_reset_tokens.user_id
                WHERE password_reset_tokens.token_hash = ?
                  AND password_reset_tokens.used_at IS NULL
                  AND password_reset_tokens.expires_at > ?
                """,
                (_hash_token(token), now),
            ).fetchone()
            if row is None or row["user_status"] != "active":
                raise ValueError("Reset link is invalid or expired.")
            password_hash, password_salt = self._password_hash(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (password_hash, password_salt, row["user_id"]),
            )
            conn.execute(
                "UPDATE users SET must_change_password = 0 WHERE id = ?", (row["user_id"],),
            )
            self._revoke_credentials(conn, row["user_id"])
        return self.get_user(row["user_id"]) or {}

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._public_user(row)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (_normalize_email(email),)).fetchone()
        return self._public_user(row)

    def create_session(self, user_id: str, request: Request) -> AuthSession:
        token = secrets.token_urlsafe(40)
        expires_at = _utc_now() + timedelta(days=self.session_days)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, last_seen_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    _hash_token(token),
                    _iso_now(),
                    expires_at.isoformat(),
                    _iso_now(),
                    _safe_ip(request),
                    request.headers.get("user-agent", "")[:300],
                ),
            )
        return AuthSession(token=token, expires_at=expires_at)

    def set_session_cookie(self, response: Response, session: AuthSession) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.token,
            expires=session.expires_at,
            max_age=self.session_days * 24 * 60 * 60,
            httponly=True,
            secure=self.cookie_secure,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (_iso_now(), _hash_token(token)),
            )

    def user_from_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        now = _iso_now()
        idle_cutoff = (_utc_now() - timedelta(hours=self.session_idle_hours)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                  AND sessions.revoked_at IS NULL
                  AND sessions.expires_at > ?
                  AND COALESCE(sessions.last_seen_at, sessions.created_at) > ?
                  AND users.status = 'active'
                """,
                (_hash_token(token), now, idle_cutoff),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, _hash_token(token)),
                )
        return self._public_user(row)

    def user_from_request(self, request: Request) -> dict[str, Any] | None:
        return self.user_from_token(request.cookies.get(SESSION_COOKIE_NAME))

    def enforce_request_rate_limit(
        self,
        *,
        request: Request,
        scope: str,
        email: str = "",
        ip_limit: int,
        email_limit: int,
        window_seconds: int,
    ) -> None:
        self.enforce_rate_limit(
            scope=f"{scope}:ip",
            key_value=_safe_ip(request),
            limit=ip_limit,
            window_seconds=window_seconds,
        )
        if email.strip():
            self.enforce_rate_limit(
                scope=f"{scope}:email",
                key_value=_normalize_email(email),
                limit=email_limit,
                window_seconds=window_seconds,
            )

    def enforce_rate_limit(
        self,
        *,
        scope: str,
        key_value: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        normalized_key = key_value.strip().lower() or "unknown"
        cutoff = (_utc_now() - timedelta(seconds=window_seconds)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_rate_events WHERE created_at < ?", ((_utc_now() - timedelta(days=1)).isoformat(),))
            count = conn.execute(
                "SELECT COUNT(*) FROM auth_rate_events WHERE scope = ? AND key_value = ? AND created_at >= ?",
                (scope, normalized_key, cutoff),
            ).fetchone()[0]
            if int(count) >= limit:
                raise RateLimitExceeded("Too many attempts. Please try again later.")
            conn.execute(
                "INSERT INTO auth_rate_events(id, scope, key_value, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), scope, normalized_key, _iso_now()),
            )

    def register_case_access(
        self,
        *,
        case_id: str,
        owner_user_id: str | None,
        source: str,
        shared: bool = False,
        expires_at: str | None = None,
    ) -> None:
        if not case_id:
            return
        with self._connect() as conn:
            existing = conn.execute("SELECT owner_user_id, source, shared FROM owned_cases WHERE id = ?", (case_id,)).fetchone()
            if existing is not None:
                if bool(existing["shared"]):
                    existing_source = str(existing["source"] or "")
                    if ":" in source and ":" not in existing_source:
                        conn.execute("UPDATE owned_cases SET source = ? WHERE id = ?", (source, case_id))
                    return
                if existing["owner_user_id"] != owner_user_id:
                    raise ValueError("Case access conflict.")
                return
            conn.execute(
                """
                INSERT INTO owned_cases(id, owner_user_id, source, shared, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case_id, owner_user_id, source, int(shared), _iso_now(), expires_at),
            )

    def can_access_case(self, *, case_id: str, user_id: str | None) -> bool:
        if not case_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT owner_user_id, shared FROM owned_cases
                WHERE id = ? AND deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                """,
                (case_id, _iso_now()),
            ).fetchone()
        return bool(row and (bool(row["shared"]) or (user_id is not None and row["owner_user_id"] == user_id)))

    def get_case_access(self, *, case_id: str) -> dict[str, Any] | None:
        if not case_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, owner_user_id, source, shared, created_at, expires_at
                FROM owned_cases
                WHERE id = ? AND deleted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
                """,
                (case_id, _iso_now()),
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["shared"] = bool(payload["shared"])
        return payload

    def list_owned_cases(self, *, user_id: str, source: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, owner_user_id, source, shared, created_at, expires_at
            FROM owned_cases
            WHERE owner_user_id = ? AND shared = 0 AND deleted_at IS NULL
              AND (expires_at IS NULL OR expires_at > ?)
        """
        params: list[Any] = [user_id, _iso_now()]
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_expired_cases(self, *, source: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, owner_user_id, source, created_at, expires_at
                FROM owned_cases
                WHERE source = ? AND shared = 0 AND deleted_at IS NULL
                  AND expires_at IS NOT NULL AND expires_at <= ?
                ORDER BY expires_at ASC
                """,
                (source, _iso_now()),
            ).fetchall()
        return [dict(row) for row in rows]

    def register_case_assets(self, *, case_id: str, asset_keys: list[str]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO case_assets(id, case_id, asset_key, created_at) VALUES (?, ?, ?, ?)",
                [(str(uuid.uuid4()), case_id, key, _iso_now()) for key in set(asset_keys)],
            )

    def can_access_asset(self, *, asset_key: str, user_id: str | None, shared_sources: set[str] | None = None) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT c.shared, c.source FROM case_assets a JOIN owned_cases c ON c.id = a.case_id
                   WHERE a.asset_key = ? AND c.deleted_at IS NULL
                     AND (c.expires_at IS NULL OR c.expires_at > ?)
                     AND (c.shared = 1 OR c.owner_user_id = ?)""",
                (asset_key, _iso_now(), user_id),
            ).fetchall()
        return any(not row["shared"] or shared_sources is None or row["source"] in shared_sources for row in rows)

    def mark_case_deleted(self, *, case_id: str, owner_user_id: str | None = None) -> bool:
        now = _iso_now()
        where = "id = ? AND deleted_at IS NULL"
        params: list[Any] = [case_id]
        if owner_user_id is not None:
            where += " AND owner_user_id = ?"
            params.append(owner_user_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(f"UPDATE owned_cases SET deleted_at = ? WHERE {where}", [now, *params])
            if cursor.rowcount:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', stage = 'failed', updated_at = ?, completed_at = ?,
                        error_message = 'Case was deleted by its owner.'
                    WHERE case_id = ? AND status IN ('queued', 'running')
                    """,
                    (now, now, case_id),
                )
        return bool(cursor.rowcount)

    def register_job(self, *, job_id: str, user_id: str, job_type: str, case_id: str | None = None) -> None:
        now = _iso_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs(
                    id, owner_user_id, case_id, job_type, status, stage,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'external', 'external', '{}', ?, ?)
                """,
                (job_id, user_id, case_id, job_type, now, now),
            )

    @staticmethod
    def _job_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        payload = dict(row)
        for column, target in (("payload_json", "payload"), ("result_json", "result")):
            raw = payload.pop(column, None)
            if not raw:
                payload[target] = None if target == "result" else {}
                continue
            try:
                decoded = json.loads(str(raw))
            except json.JSONDecodeError:
                decoded = None if target == "result" else {}
            payload[target] = decoded
        return payload

    def create_queued_job(
        self,
        *,
        user_id: str,
        job_type: str,
        payload: dict[str, Any],
        case_id: str | None = None,
        job_id: str | None = None,
        initial_result: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        now = _iso_now()
        job_id = job_id or f"job_{uuid.uuid4().hex[:16]}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                """
                SELECT * FROM jobs
                WHERE owner_user_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at ASC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if active is not None:
                existing = self._job_payload(active)
                if existing is None:  # pragma: no cover - guarded by active row.
                    raise RuntimeError("Active job disappeared while creating a queue entry.")
                return existing, False
            conn.execute(
                """
                INSERT INTO jobs(
                    id, owner_user_id, case_id, job_type, status, stage,
                    payload_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    user_id,
                    case_id,
                    job_type,
                    json.dumps(payload),
                    json.dumps(initial_result) if initial_result is not None else None,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        created = self._job_payload(row)
        if created is None:  # pragma: no cover - insertion and read share a transaction.
            raise RuntimeError("Queued job could not be read after creation.")
        return created, True

    def get_job(self, *, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_payload(row)

    def get_active_job(self, *, user_id: str, job_type: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM jobs WHERE owner_user_id = ? AND status IN ('queued', 'running')"
        params: list[Any] = [user_id]
        if job_type:
            sql += " AND job_type = ?"
            params.append(job_type)
        sql += " ORDER BY created_at ASC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._job_payload(row)

    def get_latest_job(self, *, user_id: str, job_type: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE owner_user_id = ? AND job_type = ? AND status != 'external'
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, job_type),
            ).fetchone()
        return self._job_payload(row)

    def get_latest_job_for_case(self, *, user_id: str, case_id: str, job_type: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE owner_user_id = ? AND case_id = ? AND job_type = ? AND status != 'external'
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, case_id, job_type),
            ).fetchone()
        return self._job_payload(row)

    def claim_next_job(self, *, job_type: str) -> dict[str, Any] | None:
        now = _iso_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_type = ? AND status = 'queued' ORDER BY created_at ASC LIMIT 1",
                (job_type,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running', stage = 'starting', started_at = COALESCE(started_at, ?),
                    updated_at = ?, error_message = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        return self._job_payload(claimed)

    def has_queued_job(self, *, job_type: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE job_type = ? AND status = 'queued' LIMIT 1",
                (job_type,),
            ).fetchone()
        return row is not None

    def update_job(
        self,
        *,
        job_id: str,
        status: str | None = None,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        updates = ["updated_at = ?"]
        values: list[Any] = [_iso_now()]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
            if status in TERMINAL_JOB_STATUSES:
                updates.append("completed_at = ?")
                values.append(_iso_now())
        if stage is not None:
            updates.append("stage = ?")
            values.append(stage)
        if result is not None:
            updates.append("result_json = ?")
            values.append(json.dumps(result))
        if error_message is not None:
            updates.append("error_message = ?")
            values.append(error_message)
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        updated = self._job_payload(row)
        if updated is None:
            raise KeyError(job_id)
        return updated

    def recover_running_jobs(self, *, job_type: str) -> int:
        now = _iso_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued', stage = 'queued', updated_at = ?,
                    error_message = 'Worker restarted; job returned to the queue.'
                WHERE job_type = ? AND status = 'running'
                """,
                (now, job_type),
            )
        return int(cursor.rowcount)

    def can_access_job(self, *, job_id: str, user_id: str | None) -> bool:
        if user_id is None:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT owner_user_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["owner_user_id"] == user_id)

    def record_preview_feedback(self, *, user_id: str, case_id: str | None,
                                category: str, workflow_step: str, comment: str) -> str:
        feedback_id = f"feedback_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO feedback (id, owner_user_id, case_id, category, workflow_step, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (feedback_id, user_id, case_id, category, workflow_step, comment, datetime.now(UTC).isoformat()),
            )
        return feedback_id

    def record_audit(
        self,
        *,
        user_id: str | None,
        action: str,
        resource: str,
        status: str,
        request: Request | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_metadata = metadata or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    id, user_id, action, resource, status, metadata_json, created_at, ip_address, user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    action,
                    resource,
                    status,
                    json.dumps(safe_metadata, sort_keys=True),
                    _iso_now(),
                    _safe_ip(request) if request else "",
                    request.headers.get("user-agent", "")[:300] if request else "",
                ),
            )

    def recent_audit(self, user_id: str | None, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT audit_events.*, users.email, users.name
            FROM audit_events
            LEFT JOIN users ON users.id = audit_events.user_id
        """
        params: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE audit_events.user_id = ?"
            params = (user_id,)
        query += " ORDER BY audit_events.created_at DESC LIMIT ?"
        params = (*params, max(1, min(limit, 200)))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._public_audit(row) for row in rows]

    def _public_user(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "organization": row["organization"],
            "role": row["role"],
            "status": row["status"],
            "email_verified_at": row["email_verified_at"],
            "dua_version": row["dua_version"],
            "dua_accepted_at": row["dua_accepted_at"],
            "created_at": row["created_at"],
            "last_login_at": row["last_login_at"],
            "must_change_password": bool(row["must_change_password"]),
            "account_setup_required": bool(row["must_change_password"] or not row["dua_accepted_at"]),
        }

    def _public_audit(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return {
            "id": row["id"],
            "action": row["action"],
            "resource": row["resource"],
            "status": row["status"],
            "metadata": metadata,
            "created_at": row["created_at"],
            "actor": {
                "email": row["email"],
                "name": row["name"],
            }
            if row["email"]
            else None,
        }
