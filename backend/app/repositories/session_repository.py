"""Auth-state repositories — ``user_sessions``, ``login_history``, ``mfa_secrets``, ``password_reset_tokens`` (Prompts/02 §02.5).

Sessions rotate in place (``refresh_jti`` is replaced, ``refresh_family`` stays) so a replayed cookie is recognised by
its family and the whole family can be revoked (rule 2 — reuse detection).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import LoginHistory, MfaSecret, PasswordResetToken, UserSession


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        institution_id: uuid.UUID | None,
        user_id: uuid.UUID,
        refresh_jti: str,
        refresh_family: str,
        device_label: str | None,
        platform: str | None,
        ip: str | None,
        user_agent: str | None,
        expires_at: datetime,
    ) -> UserSession:
        row = UserSession(
            institution_id=institution_id,
            user_id=user_id,
            refresh_jti=refresh_jti,
            refresh_family=refresh_family,
            device_label=device_label,
            platform=platform,
            ip=ip,
            user_agent=user_agent,
            expires_at=expires_at,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get(self, session_id: uuid.UUID) -> UserSession | None:
        return (await self.db.execute(select(UserSession).where(UserSession.id == session_id))).scalar_one_or_none()

    async def get_by_jti(self, jti: str, *, for_update: bool = False) -> UserSession | None:
        q = select(UserSession).where(UserSession.refresh_jti == jti)
        if for_update:
            q = q.with_for_update()
        return (await self.db.execute(q)).scalar_one_or_none()

    async def family_known(self, family: str) -> bool:
        return (
            await self.db.execute(select(UserSession.id).where(UserSession.refresh_family == family).limit(1))
        ).first() is not None

    async def rotate(self, session: UserSession, new_jti: str, expires_at: datetime) -> UserSession:
        session.refresh_jti = new_jti
        session.last_seen_at = datetime.now(UTC)
        session.expires_at = expires_at
        await self.db.flush()
        return session

    async def touch(self, session_id: uuid.UUID) -> None:
        await self.db.execute(
            update(UserSession).where(UserSession.id == session_id).values(last_seen_at=datetime.now(UTC))
        )

    async def revoke(self, session: UserSession, reason: str) -> None:
        if session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = reason
            await self.db.flush()

    async def revoke_family(self, family: str, reason: str) -> int:
        res: Any = await self.db.execute(
            update(UserSession)
            .where(UserSession.refresh_family == family, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return int(res.rowcount or 0)

    async def revoke_all(self, user_id: uuid.UUID, reason: str, except_session: uuid.UUID | None = None) -> int:
        stmt = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        if except_session:
            stmt = stmt.where(UserSession.id != except_session)
        res: Any = await self.db.execute(stmt)
        return int(res.rowcount or 0)

    async def list_active(self, user_id: uuid.UUID) -> Sequence[UserSession]:
        now = datetime.now(UTC)
        q = (
            select(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
            .order_by(UserSession.last_seen_at.desc())
        )
        return (await self.db.execute(q)).scalars().all()

    async def cleanup(self, now: datetime, purge_before: datetime) -> tuple[int, int]:
        """Revoke expired sessions; delete revoked/expired rows older than ``purge_before``."""
        expired: Any = await self.db.execute(
            update(UserSession)
            .where(UserSession.revoked_at.is_(None), UserSession.expires_at <= now)
            .values(revoked_at=now, revoked_reason="expired")
        )
        purged: Any = await self.db.execute(
            delete(UserSession).where(UserSession.revoked_at.is_not(None), UserSession.revoked_at < purge_before)
        )
        return int(expired.rowcount or 0), int(purged.rowcount or 0)

    async def revoke_expired_accounts(self, now: datetime) -> int:
        """Sessions of users whose ``valid_to`` has passed (Beat ``auth.expire_time_boxed_accounts``)."""
        from app.models.platform import User

        expired_users = select(User.id).where(User.valid_to.is_not(None), User.valid_to < now)
        res: Any = await self.db.execute(
            update(UserSession)
            .where(UserSession.user_id.in_(expired_users), UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason="account_expired")
        )
        return int(res.rowcount or 0)


class LoginHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        *,
        institution_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        identifier: str | None,
        outcome: str,
        ip: str | None,
        user_agent: str | None,
    ) -> LoginHistory:
        row = LoginHistory(
            institution_id=institution_id,
            user_id=user_id,
            identifier=(identifier or "")[:200] or None,
            outcome=outcome,
            ip=ip,
            user_agent=user_agent,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def for_user(self, user_id: uuid.UUID, limit: int = 50) -> Sequence[LoginHistory]:
        q = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.occurred_at.desc())
            .limit(limit)
        )
        return (await self.db.execute(q)).scalars().all()


class MfaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: uuid.UUID) -> MfaSecret | None:
        return (await self.db.execute(select(MfaSecret).where(MfaSecret.user_id == user_id))).scalar_one_or_none()

    async def upsert_pending(self, user_id: uuid.UUID, secret_encrypted: bytes) -> MfaSecret:
        row = await self.get(user_id)
        if row is None:
            row = MfaSecret(user_id=user_id, secret_encrypted=secret_encrypted, recovery_codes_hashed=[])
            self.db.add(row)
        else:
            row.secret_encrypted = secret_encrypted
            row.confirmed_at = None
            row.recovery_codes_hashed = []
        await self.db.flush()
        return row

    async def delete(self, user_id: uuid.UUID) -> None:
        await self.db.execute(delete(MfaSecret).where(MfaSecret.user_id == user_id))


class PasswordResetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: uuid.UUID, token_hash: str, ttl_minutes: int) -> PasswordResetToken:
        row = PasswordResetToken(
            user_id=user_id, token_hash=token_hash, expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def get_valid(self, token_hash: str) -> PasswordResetToken | None:
        now = datetime.now(UTC)
        q = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def mark_used(self, row: PasswordResetToken) -> None:
        row.used_at = datetime.now(UTC)
        await self.db.flush()

    async def purge_expired(self, now: datetime) -> int:
        res: Any = await self.db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now))
        return int(res.rowcount or 0)
