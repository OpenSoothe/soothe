"""IdentityProtocol implementation. RFC-307.

Provides AKSK-based authentication and JWT token management for soothe-daemon.
Uses existing PersistenceProtocol backend for storage (tables added to same DB).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from soothe_sdk.protocols.identity import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityProtocol,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)

from soothe.core.security.credentials import (
    generate_access_key,
    generate_aksk_id,
    generate_secret_key,
    hash_secret_key,
    is_valid_access_key_format,
    verify_secret_key,
)
from soothe.core.security.errors import (
    AKSKNotFoundError,
    MappingConflictError,
    MappingNotFoundError,
    UserNotFoundError,
)
from soothe.core.security.tokens import (
    JWTManager,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class IdentityService(IdentityProtocol):
    """IdentityProtocol implementation using SQLite backend.

    RFC-307 §Protocol Interface implementation.

    This service provides:
    - User creation and management
    - AKSK credential provisioning
    - JWT token generation and validation
    - Token revocation tracking
    - External channel identity mapping

    Storage uses the same SQLite database as StrangeLoop persistence
    (tables added via initialize_identity_tables_sync).
    """

    def __init__(
        self,
        db_path: Path,
        jwt_key: str,
        access_expiry_hours: int = 1,
        refresh_expiry_days: int = 7,
        default_aksk_expiry_days: int | None = 90,
        max_aksk_expiry_days: int = 365,
        enabled: bool = True,
    ) -> None:
        """Initialize IdentityService.

        Args:
            db_path: Path to SQLite database (shared with StrangeLoop persistence).
            jwt_key: JWT signing key (256-bit recommended).
            access_expiry_hours: Access token expiry hours (1-24).
            refresh_expiry_days: Refresh token expiry days (1-365).
            default_aksk_expiry_days: Default AKSK expiry, None = never.
            max_aksk_expiry_days: Maximum AKSK expiry days.
            enabled: Service enabled status.

        RFC-307 §Configuration.
        """
        self.db_path = db_path
        self.enabled = enabled
        self.default_aksk_expiry_days = default_aksk_expiry_days
        self.max_aksk_expiry_days = max_aksk_expiry_days

        self._jwt_manager = JWTManager(
            signing_key=jwt_key,
            access_expiry_hours=access_expiry_hours,
            refresh_expiry_days=refresh_expiry_days,
        )

        # Connection pool (similar to SQLitePersistenceBackend pattern)
        self._writer_conn: sqlite3.Connection | None = None
        self._writer_thread_lock = threading.Lock()
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of database tables."""
        if self._writer_conn is None:
            async with self._init_lock:
                if self._writer_conn is None:
                    await asyncio.to_thread(self._init_writer_sync)

    def _init_writer_sync(self) -> None:
        """Initialize writer connection and create identity tables."""
        with self._writer_thread_lock:
            if self._writer_conn is not None:
                return

            # Ensure database directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create identity tables
            initialize_identity_tables_sync(self.db_path)

            # Create writer connection
            self._writer_conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )
            self._writer_conn.execute("PRAGMA foreign_keys=ON")
            self._writer_conn.execute("PRAGMA journal_mode=WAL")

            logger.info("IdentityService initialized: db=%s", self.db_path)

    async def _writer_to_thread(self, sync_fn: Callable[..., T], *args: Any) -> T:
        """Run sync_fn on writer connection with thread safety."""
        await self._ensure_initialized()
        return await asyncio.to_thread(self._exec_on_writer_locked, sync_fn, *args)

    def _exec_on_writer_locked(self, sync_fn: Callable[..., T], *args: Any) -> T:
        """Execute function on writer connection with lock."""
        with self._writer_thread_lock:
            conn = self._writer_conn
            if conn is None:
                raise RuntimeError("IdentityService writer connection not initialized")
            return sync_fn(conn, *args)

    # -----------------------------------------------------------------------
    # User Management
    # -----------------------------------------------------------------------

    def create_user(self, user_id: str, metadata: dict | None = None) -> User:
        """Create a new user. RFC-307 §User."""
        return asyncio.get_event_loop().run_until_complete(
            self._create_user_async(user_id, metadata)
        )

    async def _create_user_async(self, user_id: str, metadata: dict | None = None) -> User:
        """Async implementation of create_user."""
        now = datetime.now(UTC)
        user = User(user_id=user_id, created_at=now, metadata=metadata or {})

        await self._writer_to_thread(
            self._create_user_sync,
            user.user_id,
            user.created_at.isoformat(),
            json.dumps(user.metadata),
        )

        logger.info("User created: user_id=%s", user_id)
        return user

    def _create_user_sync(
        self, conn: sqlite3.Connection, user_id: str, created_at: str, metadata: str
    ) -> None:
        """Sync: insert user."""
        conn.execute(
            """
            INSERT INTO identity_users (user_id, created_at, metadata)
            VALUES (?, ?, ?)
            """,
            (user_id, created_at, metadata),
        )
        conn.commit()

    def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        return asyncio.get_event_loop().run_until_complete(self._get_user_async(user_id))

    async def _get_user_async(self, user_id: str) -> User | None:
        """Async implementation of get_user."""
        row = await self._writer_to_thread(self._get_user_sync, user_id)
        if row is None:
            return None
        return User(
            user_id=row[0],
            created_at=datetime.fromisoformat(row[1]),
            metadata=json.loads(row[2]) if row[2] else {},
        )

    def _get_user_sync(self, conn: sqlite3.Connection, user_id: str) -> tuple | None:
        """Sync: get user."""
        cursor = conn.execute(
            "SELECT user_id, created_at, metadata FROM identity_users WHERE user_id = ?",
            (user_id,),
        )
        return cursor.fetchone()

    def list_users(self) -> list[User]:
        """List all users."""
        return asyncio.get_event_loop().run_until_complete(self._list_users_async())

    async def _list_users_async(self) -> list[User]:
        """Async implementation of list_users."""
        rows = await self._writer_to_thread(self._list_users_sync)
        return [
            User(
                user_id=row[0],
                created_at=datetime.fromisoformat(row[1]),
                metadata=json.loads(row[2]) if row[2] else {},
            )
            for row in rows
        ]

    def _list_users_sync(self, conn: sqlite3.Connection) -> list[tuple]:
        """Sync: list users."""
        cursor = conn.execute(
            "SELECT user_id, created_at, metadata FROM identity_users ORDER BY created_at"
        )
        return cursor.fetchall()

    def delete_user(self, user_id: str) -> None:
        """Delete user and revoke all credentials."""
        asyncio.get_event_loop().run_until_complete(self._delete_user_async(user_id))

    async def _delete_user_async(self, user_id: str) -> None:
        """Async implementation of delete_user."""
        # Check user exists
        user = await self._get_user_async(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        # Revoke all AKSK and tokens
        await self._writer_to_thread(self._delete_user_sync, user_id)
        logger.info("User deleted: user_id=%s (all credentials revoked)", user_id)

    def _delete_user_sync(self, conn: sqlite3.Connection, user_id: str) -> None:
        """Sync: delete user and cascade."""
        now_iso = datetime.now(UTC).isoformat()

        # Collect all JTIs for revocation tracking before deletion
        cursor = conn.execute(
            "SELECT jti FROM identity_tokens WHERE user_id = ?",
            (user_id,),
        )
        for row in cursor.fetchall():
            conn.execute(
                """
                INSERT OR IGNORE INTO identity_revoked_jtis (jti, revoked_at, reason)
                VALUES (?, ?, 'user_deleted')
                """,
                (row[0], now_iso),
            )

        # Delete tokens (child of aksk_pairs, must delete before aksk)
        conn.execute(
            "DELETE FROM identity_tokens WHERE user_id = ?",
            (user_id,),
        )

        # Delete AKSK pairs (child of users, must delete before user)
        conn.execute(
            "DELETE FROM identity_aksk_pairs WHERE user_id = ?",
            (user_id,),
        )

        # Delete external mappings
        conn.execute(
            "DELETE FROM identity_external_mappings WHERE user_id = ?",
            (user_id,),
        )

        # Delete user
        conn.execute("DELETE FROM identity_users WHERE user_id = ?", (user_id,))
        conn.commit()

    # -----------------------------------------------------------------------
    # AKSK Management
    # -----------------------------------------------------------------------

    def create_aksk(self, user_id: str, expiry_days: int | None = None) -> AKSKPair:
        """Create AKSK pair for user. RFC-307 §AKSKPair."""
        return asyncio.get_event_loop().run_until_complete(
            self._create_aksk_async(user_id, expiry_days)
        )

    async def _create_aksk_async(self, user_id: str, expiry_days: int | None = None) -> AKSKPair:
        """Async implementation of create_aksk."""
        # Check user exists
        user = await self._get_user_async(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        # Apply expiry defaults
        if expiry_days is None:
            expiry_days = self.default_aksk_expiry_days
        if expiry_days is not None and expiry_days > self.max_aksk_expiry_days:
            raise ValueError(f"expiry_days exceeds maximum ({self.max_aksk_expiry_days})")

        # Generate credentials
        aksk_id = generate_aksk_id()
        access_key = generate_access_key()
        secret_key = generate_secret_key()  # Plaintext, returned once
        secret_key_hash = hash_secret_key(secret_key)

        now = datetime.now(UTC)
        expires_at = None
        if expiry_days is not None:
            expires_at = now + timedelta(days=expiry_days)

        aksk = AKSKPair(
            aksk_id=aksk_id,
            user_id=user_id,
            access_key=access_key,
            secret_key_hash=secret_key_hash,
            created_at=now,
            expires_at=expires_at,
        )

        await self._writer_to_thread(
            self._create_aksk_sync,
            aksk.aksk_id,
            aksk.user_id,
            aksk.access_key,
            aksk.secret_key_hash,
            aksk.created_at.isoformat(),
            aksk.expires_at.isoformat() if aksk.expires_at else None,
        )

        # Return with plaintext secret_key (one-time only)
        logger.info(
            "AKSK created: aksk_id=%s user=%s expires=%s",
            aksk_id,
            user_id,
            expires_at,
        )
        return aksk

    def _create_aksk_sync(
        self,
        conn: sqlite3.Connection,
        aksk_id: str,
        user_id: str,
        access_key: str,
        secret_key_hash: str,
        created_at: str,
        expires_at: str | None,
    ) -> None:
        """Sync: insert AKSK."""
        conn.execute(
            """
            INSERT INTO identity_aksk_pairs
            (aksk_id, user_id, access_key, secret_key_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (aksk_id, user_id, access_key, secret_key_hash, created_at, expires_at),
        )
        conn.commit()

    def list_aksk(self, user_id: str) -> list[AKSKPair]:
        """List AKSK pairs for user."""
        return asyncio.get_event_loop().run_until_complete(self._list_aksk_async(user_id))

    async def _list_aksk_async(self, user_id: str) -> list[AKSKPair]:
        """Async implementation of list_aksk."""
        rows = await self._writer_to_thread(self._list_aksk_sync, user_id)
        return [
            AKSKPair(
                aksk_id=row[0],
                user_id=row[1],
                access_key=row[2],
                secret_key_hash=row[3],
                created_at=datetime.fromisoformat(row[4]),
                expires_at=datetime.fromisoformat(row[5]) if row[5] else None,
                revoked=bool(row[6]),
                revoked_at=datetime.fromisoformat(row[7]) if row[7] else None,
            )
            for row in rows
        ]

    def _list_aksk_sync(self, conn: sqlite3.Connection, user_id: str) -> list[tuple]:
        """Sync: list AKSK."""
        cursor = conn.execute(
            """
            SELECT aksk_id, user_id, access_key, secret_key_hash, created_at,
                   expires_at, revoked, revoked_at
            FROM identity_aksk_pairs
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()

    def revoke_aksk(self, aksk_id: str) -> None:
        """Revoke AKSK and all related tokens."""
        asyncio.get_event_loop().run_until_complete(self._revoke_aksk_async(aksk_id))

    async def _revoke_aksk_async(self, aksk_id: str) -> None:
        """Async implementation of revoke_aksk."""
        now = datetime.now(UTC)

        # Check AKSK exists
        row = await self._writer_to_thread(self._get_aksk_sync, aksk_id)
        if row is None:
            raise AKSKNotFoundError(aksk_id)

        # Revoke AKSK and cascade to tokens
        await self._writer_to_thread(self._revoke_aksk_sync, aksk_id, now.isoformat())
        logger.info("AKSK revoked: aksk_id=%s (all tokens revoked)", aksk_id)

    def _get_aksk_sync(self, conn: sqlite3.Connection, aksk_id: str) -> tuple | None:
        """Sync: get AKSK."""
        cursor = conn.execute(
            "SELECT aksk_id FROM identity_aksk_pairs WHERE aksk_id = ?",
            (aksk_id,),
        )
        return cursor.fetchone()

    def _revoke_aksk_sync(self, conn: sqlite3.Connection, aksk_id: str, revoked_at: str) -> None:
        """Sync: revoke AKSK and cascade."""
        # Mark AKSK as revoked
        conn.execute(
            """
            UPDATE identity_aksk_pairs
            SET revoked = 1, revoked_at = ?
            WHERE aksk_id = ? AND revoked = 0
            """,
            (revoked_at, aksk_id),
        )

        # Get all tokens for this AKSK
        cursor = conn.execute(
            "SELECT jti FROM identity_tokens WHERE aksk_id = ? AND revoked = 0",
            (aksk_id,),
        )
        jtis = [row[0] for row in cursor.fetchall()]

        # Mark tokens as revoked
        conn.execute(
            """
            UPDATE identity_tokens
            SET revoked = 1, revoked_at = ?
            WHERE aksk_id = ? AND revoked = 0
            """,
            (revoked_at, aksk_id),
        )

        # Add to revoked_jtis
        for jti in jtis:
            conn.execute(
                """
                INSERT OR IGNORE INTO identity_revoked_jtis (jti, revoked_at, reason)
                VALUES (?, ?, 'aksk_revoked')
                """,
                (jti, revoked_at),
            )

        conn.commit()

    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------

    def authenticate(self, access_key: str, secret_key: str) -> AuthResult | None:
        """Authenticate with AKSK credentials. RFC-307 §Authentication Flow."""
        return asyncio.get_event_loop().run_until_complete(
            self._authenticate_async(access_key, secret_key)
        )

    async def _authenticate_async(self, access_key: str, secret_key: str) -> AuthResult | None:
        """Async implementation of authenticate."""
        # Validate format
        if not is_valid_access_key_format(access_key):
            return None

        # Lookup AKSK
        row = await self._writer_to_thread(self._get_aksk_by_access_key_sync, access_key)
        if row is None:
            # No timing attack hint - use constant comparison
            verify_secret_key(secret_key, "invalid_hash_placeholder")
            return None

        aksk_id, user_id, secret_key_hash, expires_at, revoked = row

        # Check revoked
        if revoked:
            return None

        # Check expiry
        if expires_at:
            expires_dt = datetime.fromisoformat(expires_at)
            if datetime.now(UTC) > expires_dt:
                return None

        # Verify secret key (constant-time)
        if not verify_secret_key(secret_key, secret_key_hash):
            return None

        # Generate tokens
        access_token, access_claims = self._jwt_manager.generate_access_token(user_id, aksk_id)
        refresh_token, refresh_claims = self._jwt_manager.generate_refresh_token(user_id, aksk_id)

        # Store JTIs
        await self._writer_to_thread(
            self._store_tokens_sync,
            access_claims.jti,
            user_id,
            aksk_id,
            "access",
            access_claims.issued_at.isoformat(),
            access_claims.expires_at.isoformat(),
            refresh_claims.jti,
            refresh_claims.issued_at.isoformat(),
            refresh_claims.expires_at.isoformat(),
        )

        logger.info("Authentication successful: user=%s aksk=%s", user_id, aksk_id)

        return AuthResult(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            expires_in=self._jwt_manager.get_token_expiry_seconds(),
        )

    def _get_aksk_by_access_key_sync(
        self, conn: sqlite3.Connection, access_key: str
    ) -> tuple | None:
        """Sync: get AKSK by access_key."""
        cursor = conn.execute(
            """
            SELECT aksk_id, user_id, secret_key_hash, expires_at, revoked
            FROM identity_aksk_pairs
            WHERE access_key = ?
            """,
            (access_key,),
        )
        return cursor.fetchone()

    def _store_tokens_sync(
        self,
        conn: sqlite3.Connection,
        access_jti: str,
        user_id: str,
        aksk_id: str,
        access_type: str,
        access_issued: str,
        access_expires: str,
        refresh_jti: str,
        refresh_issued: str,
        refresh_expires: str,
    ) -> None:
        """Sync: store token JTIs."""
        conn.execute(
            """
            INSERT INTO identity_tokens
            (jti, user_id, aksk_id, token_type, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (access_jti, user_id, aksk_id, access_type, access_issued, access_expires),
        )
        conn.execute(
            """
            INSERT INTO identity_tokens
            (jti, user_id, aksk_id, token_type, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (refresh_jti, user_id, aksk_id, "refresh", refresh_issued, refresh_expires),
        )
        conn.commit()

    def validate_token(self, token: str) -> TokenClaims | None:
        """Validate JWT token. RFC-307 §Authentication Flow."""
        return asyncio.get_event_loop().run_until_complete(self._validate_token_async(token))

    async def _validate_token_async(self, token: str) -> TokenClaims | None:
        """Async implementation of validate_token."""
        # JWT validation (signature, expiry)
        claims = self._jwt_manager.validate_token(token)
        if claims is None:
            return None

        # Check revocation
        is_revoked = await self._writer_to_thread(self._check_jti_revoked_sync, claims.jti)
        if is_revoked:
            return None

        return claims

    def _check_jti_revoked_sync(self, conn: sqlite3.Connection, jti: str) -> bool:
        """Sync: check if JTI is revoked."""
        cursor = conn.execute(
            "SELECT 1 FROM identity_revoked_jtis WHERE jti = ?",
            (jti,),
        )
        return cursor.fetchone() is not None

    def refresh_token(self, refresh_token: str) -> TokenRefreshResult | None:
        """Refresh tokens using refresh_token. RFC-307 §Token Refresh Flow."""
        return asyncio.get_event_loop().run_until_complete(self._refresh_token_async(refresh_token))

    async def _refresh_token_async(self, refresh_token: str) -> TokenRefreshResult | None:
        """Async implementation of refresh_token."""
        # Validate refresh token JWT
        claims = self._jwt_manager.validate_token(refresh_token)
        if claims is None:
            return None

        # Must be refresh token type
        if claims.token_type != "refresh":
            return None

        # Check revocation
        is_revoked = await self._writer_to_thread(self._check_jti_revoked_sync, claims.jti)
        if is_revoked:
            return None

        # Generate new tokens
        access_token, access_claims = self._jwt_manager.generate_access_token(
            claims.user_id, claims.aksk_id
        )
        refresh_token_new, refresh_claims = self._jwt_manager.generate_refresh_token(
            claims.user_id, claims.aksk_id
        )

        # Revoke old tokens (rotation)
        now = datetime.now(UTC)
        await self._writer_to_thread(
            self._rotate_tokens_sync,
            claims.jti,  # Old refresh JTI
            now.isoformat(),
            access_claims.jti,
            claims.user_id,
            claims.aksk_id,
            access_claims.issued_at.isoformat(),
            access_claims.expires_at.isoformat(),
            refresh_claims.jti,
            refresh_claims.issued_at.isoformat(),
            refresh_claims.expires_at.isoformat(),
        )

        logger.info(
            "Token refreshed: user=%s old_jti=%s",
            claims.user_id,
            claims.jti,
        )

        return TokenRefreshResult(
            access_token=access_token,
            refresh_token=refresh_token_new,
            expires_in=self._jwt_manager.get_token_expiry_seconds(),
        )

    def _rotate_tokens_sync(
        self,
        conn: sqlite3.Connection,
        old_jti: str,
        revoked_at: str,
        new_access_jti: str,
        user_id: str,
        aksk_id: str,
        access_issued: str,
        access_expires: str,
        new_refresh_jti: str,
        refresh_issued: str,
        refresh_expires: str,
    ) -> None:
        """Sync: rotate tokens (revoke old, store new)."""
        # Mark old refresh token as revoked
        conn.execute(
            """
            UPDATE identity_tokens
            SET revoked = 1, revoked_at = ?
            WHERE jti = ?
            """,
            (revoked_at, old_jti),
        )

        # Add to revoked_jtis
        conn.execute(
            """
            INSERT OR IGNORE INTO identity_revoked_jtis (jti, revoked_at, reason)
            VALUES (?, ?, 'refresh_used')
            """,
            (old_jti, revoked_at),
        )

        # Store new tokens
        conn.execute(
            """
            INSERT INTO identity_tokens
            (jti, user_id, aksk_id, token_type, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_access_jti, user_id, aksk_id, "access", access_issued, access_expires),
        )
        conn.execute(
            """
            INSERT INTO identity_tokens
            (jti, user_id, aksk_id, token_type, issued_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_refresh_jti, user_id, aksk_id, "refresh", refresh_issued, refresh_expires),
        )

        conn.commit()

    # -----------------------------------------------------------------------
    # Token Management
    # -----------------------------------------------------------------------

    def revoke_token(self, jti: str) -> None:
        """Revoke token by JTI."""
        asyncio.get_event_loop().run_until_complete(self._revoke_token_async(jti))

    async def _revoke_token_async(self, jti: str) -> None:
        """Async implementation of revoke_token."""
        now = datetime.now(UTC)
        await self._writer_to_thread(self._revoke_token_sync, jti, now.isoformat())
        logger.info("Token revoked: jti=%s", jti)

    def _revoke_token_sync(self, conn: sqlite3.Connection, jti: str, revoked_at: str) -> None:
        """Sync: revoke token."""
        conn.execute(
            """
            UPDATE identity_tokens
            SET revoked = 1, revoked_at = ?
            WHERE jti = ?
            """,
            (revoked_at, jti),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO identity_revoked_jtis (jti, revoked_at, reason)
            VALUES (?, ?, 'admin_revoked')
            """,
            (jti, revoked_at),
        )
        conn.commit()

    def revoke_all_tokens(self, user_id: str) -> None:
        """Revoke all tokens for user."""
        asyncio.get_event_loop().run_until_complete(self._revoke_all_tokens_async(user_id))

    async def _revoke_all_tokens_async(self, user_id: str) -> None:
        """Async implementation of revoke_all_tokens."""
        now = datetime.now(UTC)
        await self._writer_to_thread(self._revoke_all_tokens_sync, user_id, now.isoformat())
        logger.info("All tokens revoked: user=%s", user_id)

    def _revoke_all_tokens_sync(
        self, conn: sqlite3.Connection, user_id: str, revoked_at: str
    ) -> None:
        """Sync: revoke all user tokens."""
        # Get all JTIs
        cursor = conn.execute(
            "SELECT jti FROM identity_tokens WHERE user_id = ? AND revoked = 0",
            (user_id,),
        )
        jtis = [row[0] for row in cursor.fetchall()]

        # Mark all as revoked
        conn.execute(
            """
            UPDATE identity_tokens
            SET revoked = 1, revoked_at = ?
            WHERE user_id = ? AND revoked = 0
            """,
            (revoked_at, user_id),
        )

        # Add to revoked_jtis
        for jti in jtis:
            conn.execute(
                """
                INSERT OR IGNORE INTO identity_revoked_jtis (jti, revoked_at, reason)
                VALUES (?, ?, 'admin_revoked')
                """,
                (jti, revoked_at),
            )

        conn.commit()

    def list_tokens(self, user_id: str, active_only: bool = False) -> list[TokenInfo]:
        """List tokens for user."""
        return asyncio.get_event_loop().run_until_complete(
            self._list_tokens_async(user_id, active_only)
        )

    async def _list_tokens_async(self, user_id: str, active_only: bool) -> list[TokenInfo]:
        """Async implementation of list_tokens."""
        rows = await self._writer_to_thread(self._list_tokens_sync, user_id, active_only)
        return [
            TokenInfo(
                jti=row[0],
                user_id=row[1],
                aksk_id=row[2],
                token_type=row[3],
                issued_at=datetime.fromisoformat(row[4]),
                expires_at=datetime.fromisoformat(row[5]),
                revoked=bool(row[6]),
            )
            for row in rows
        ]

    def _list_tokens_sync(
        self, conn: sqlite3.Connection, user_id: str, active_only: bool
    ) -> list[tuple]:
        """Sync: list tokens."""
        if active_only:
            cursor = conn.execute(
                """
                SELECT jti, user_id, aksk_id, token_type, issued_at, expires_at, revoked
                FROM identity_tokens
                WHERE user_id = ? AND revoked = 0 AND expires_at > ?
                ORDER BY issued_at DESC
                """,
                (user_id, datetime.now(UTC).isoformat()),
            )
        else:
            cursor = conn.execute(
                """
                SELECT jti, user_id, aksk_id, token_type, issued_at, expires_at, revoked
                FROM identity_tokens
                WHERE user_id = ?
                ORDER BY issued_at DESC
                """,
                (user_id,),
            )
        return cursor.fetchall()

    # -----------------------------------------------------------------------
    # External Identity Mapping
    # -----------------------------------------------------------------------

    def map_external_identity(
        self, channel: str, sender_id: str, user_id: str
    ) -> ExternalIdentityMapping:
        """Map external channel sender to soothe user. RFC-307 §ExternalIdentityMapping."""
        return asyncio.get_event_loop().run_until_complete(
            self._map_external_async(channel, sender_id, user_id)
        )

    async def _map_external_async(
        self, channel: str, sender_id: str, user_id: str
    ) -> ExternalIdentityMapping:
        """Async implementation of map_external_identity."""
        # Check user exists
        user = await self._get_user_async(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        # Check existing mapping
        existing = await self._writer_to_thread(self._get_mapping_sync, channel, sender_id)
        if existing is not None:
            if existing[2] == user_id:
                # Same mapping exists
                return ExternalIdentityMapping(
                    mapping_id=existing[0],
                    channel=channel,
                    sender_id=sender_id,
                    user_id=user_id,
                    created_at=datetime.fromisoformat(existing[3]),
                )
            else:
                # Different user mapped
                raise MappingConflictError(
                    f"Mapping exists for {channel}:{sender_id} -> {existing[2]}"
                )

        # Create new mapping
        mapping_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        mapping = ExternalIdentityMapping(
            mapping_id=mapping_id,
            channel=channel,
            sender_id=sender_id,
            user_id=user_id,
            created_at=now,
        )

        await self._writer_to_thread(
            self._create_mapping_sync,
            mapping.mapping_id,
            mapping.channel,
            mapping.sender_id,
            mapping.user_id,
            mapping.created_at.isoformat(),
        )

        logger.info(
            "External identity mapped: channel=%s sender=%s user=%s",
            channel,
            sender_id,
            user_id,
        )
        return mapping

    def _get_mapping_sync(
        self, conn: sqlite3.Connection, channel: str, sender_id: str
    ) -> tuple | None:
        """Sync: get mapping."""
        cursor = conn.execute(
            """
            SELECT mapping_id, channel, user_id, created_at
            FROM identity_external_mappings
            WHERE channel = ? AND sender_id = ?
            """,
            (channel, sender_id),
        )
        return cursor.fetchone()

    def _create_mapping_sync(
        self,
        conn: sqlite3.Connection,
        mapping_id: str,
        channel: str,
        sender_id: str,
        user_id: str,
        created_at: str,
    ) -> None:
        """Sync: create mapping."""
        conn.execute(
            """
            INSERT INTO identity_external_mappings
            (mapping_id, channel, sender_id, user_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mapping_id, channel, sender_id, user_id, created_at),
        )
        conn.commit()

    def resolve_identity(self, channel: str, sender_id: str) -> str | None:
        """Resolve external sender to user_id. RFC-307 §External Channel Resolution."""
        return asyncio.get_event_loop().run_until_complete(
            self._resolve_identity_async(channel, sender_id)
        )

    async def _resolve_identity_async(self, channel: str, sender_id: str) -> str | None:
        """Async implementation of resolve_identity."""
        row = await self._writer_to_thread(self._get_mapping_sync, channel, sender_id)
        if row is None:
            return None
        return row[2]  # user_id

    def list_mappings(
        self, channel: str | None = None, user_id: str | None = None
    ) -> list[ExternalIdentityMapping]:
        """List external identity mappings."""
        return asyncio.get_event_loop().run_until_complete(
            self._list_mappings_async(channel, user_id)
        )

    async def _list_mappings_async(
        self, channel: str | None, user_id: str | None
    ) -> list[ExternalIdentityMapping]:
        """Async implementation of list_mappings."""
        rows = await self._writer_to_thread(self._list_mappings_sync, channel, user_id)
        return [
            ExternalIdentityMapping(
                mapping_id=row[0],
                channel=row[1],
                sender_id=row[2],
                user_id=row[3],
                created_at=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]

    def _list_mappings_sync(
        self, conn: sqlite3.Connection, channel: str | None, user_id: str | None
    ) -> list[tuple]:
        """Sync: list mappings."""
        if channel and user_id:
            cursor = conn.execute(
                """
                SELECT mapping_id, channel, sender_id, user_id, created_at
                FROM identity_external_mappings
                WHERE channel = ? AND user_id = ?
                ORDER BY created_at DESC
                """,
                (channel, user_id),
            )
        elif channel:
            cursor = conn.execute(
                """
                SELECT mapping_id, channel, sender_id, user_id, created_at
                FROM identity_external_mappings
                WHERE channel = ?
                ORDER BY created_at DESC
                """,
                (channel,),
            )
        elif user_id:
            cursor = conn.execute(
                """
                SELECT mapping_id, channel, sender_id, user_id, created_at
                FROM identity_external_mappings
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT mapping_id, channel, sender_id, user_id, created_at
                FROM identity_external_mappings
                ORDER BY created_at DESC
                """
            )
        return cursor.fetchall()

    def unmap_external(self, channel: str, sender_id: str) -> None:
        """Remove external identity mapping."""
        asyncio.get_event_loop().run_until_complete(self._unmap_external_async(channel, sender_id))

    async def _unmap_external_async(self, channel: str, sender_id: str) -> None:
        """Async implementation of unmap_external."""
        existing = await self._writer_to_thread(self._get_mapping_sync, channel, sender_id)
        if existing is None:
            raise MappingNotFoundError(f"{channel}:{sender_id}")

        await self._writer_to_thread(self._delete_mapping_sync, channel, sender_id)
        logger.info("External mapping removed: channel=%s sender=%s", channel, sender_id)

    def _delete_mapping_sync(self, conn: sqlite3.Connection, channel: str, sender_id: str) -> None:
        """Sync: delete mapping."""
        conn.execute(
            """
            DELETE FROM identity_external_mappings
            WHERE channel = ? AND sender_id = ?
            """,
            (channel, sender_id),
        )
        conn.commit()

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def get_status(self) -> IdentityStatus:
        """Get identity service status."""
        return asyncio.get_event_loop().run_until_complete(self._get_status_async())

    async def _get_status_async(self) -> IdentityStatus:
        """Async implementation of get_status."""
        counts = await self._writer_to_thread(self._get_counts_sync)
        return IdentityStatus(
            enabled=self.enabled,
            storage_backend="sqlite",
            jwt_key_source="config",  # TODO: track actual source
            users_count=counts[0],
            active_aksk_count=counts[1],
            active_tokens_count=counts[2],
        )

    def _get_counts_sync(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Sync: get counts."""
        cursor = conn.execute("SELECT COUNT(*) FROM identity_users")
        users = cursor.fetchone()[0]

        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM identity_aksk_pairs
            WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?)
            """,
            (datetime.now(UTC).isoformat(),),
        )
        active_aksk = cursor.fetchone()[0]

        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM identity_tokens
            WHERE revoked = 0 AND expires_at > ?
            """,
            (datetime.now(UTC).isoformat(),),
        )
        active_tokens = cursor.fetchone()[0]

        return (users, active_aksk, active_tokens)


def initialize_identity_tables_sync(db_path: Path) -> None:
    """Initialize identity tables in SQLite database.

    Tables are added to the same database as StrangeLoop persistence.
    RFC-307 §Storage Schema.

    Args:
        db_path: Path to SQLite database file.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")

        # Users table
        db.execute("""
            CREATE TABLE IF NOT EXISTS identity_users (
                user_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                metadata TEXT
            )
        """)

        # AKSK pairs table
        db.execute("""
            CREATE TABLE IF NOT EXISTS identity_aksk_pairs (
                aksk_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES identity_users(user_id),
                access_key TEXT NOT NULL UNIQUE,
                secret_key_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked INTEGER NOT NULL DEFAULT 0,
                revoked_at TEXT
            )
        """)

        # Tokens table (for revocation tracking)
        db.execute("""
            CREATE TABLE IF NOT EXISTS identity_tokens (
                jti TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                aksk_id TEXT NOT NULL REFERENCES identity_aksk_pairs(aksk_id),
                token_type TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                revoked_at TEXT
            )
        """)

        # External identity mappings table
        db.execute("""
            CREATE TABLE IF NOT EXISTS identity_external_mappings (
                mapping_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES identity_users(user_id),
                created_at TEXT NOT NULL,
                UNIQUE(channel, sender_id)
            )
        """)

        # Revoked JTIs table (fast lookup)
        db.execute("""
            CREATE TABLE IF NOT EXISTS identity_revoked_jtis (
                jti TEXT PRIMARY KEY,
                revoked_at TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)

        # Create indexes
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_identity_aksk_user
            ON identity_aksk_pairs(user_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_identity_tokens_user
            ON identity_tokens(user_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_identity_tokens_aksk
            ON identity_tokens(aksk_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_identity_mappings_channel_sender
            ON identity_external_mappings(channel, sender_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_identity_mappings_user
            ON identity_external_mappings(user_id)
        """)

        db.commit()
        logger.info("Identity tables initialized: db=%s", db_path)
