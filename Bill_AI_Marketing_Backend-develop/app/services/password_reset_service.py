import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.config import Config
from app.extensions import db
from app.models.password_reset_token import PasswordResetToken


def _hash_token(raw_token: str) -> str:
    secret = Config.SECRET_KEY or Config.JWT_SECRET_KEY
    if not secret:
        raise ValueError("SECRET_KEY (or JWT_SECRET_KEY) must be set for password reset")
    data = f"{raw_token}:{secret}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def create_reset_token(user_id: str) -> Tuple[str, PasswordResetToken]:
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw)
    expires_at = datetime.utcnow() + timedelta(minutes=Config.PASSWORD_RESET_TOKEN_EXPIRES_MINUTES)

    record = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        used_at=None,
    )
    db.session.add(record)
    db.session.commit()
    return raw, record


def find_valid_token(raw_token: str) -> Optional[PasswordResetToken]:
    token_hash = _hash_token(raw_token)
    now = datetime.utcnow()
    return PasswordResetToken.query.filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).first()


def mark_token_used(token: PasswordResetToken) -> None:
    token.used_at = datetime.utcnow()
    db.session.commit()

