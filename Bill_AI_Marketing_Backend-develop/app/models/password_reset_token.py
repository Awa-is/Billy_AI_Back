from app.extensions import db
from datetime import datetime
import uuid


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'

    token_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)

    token_hash = db.Column(db.String(64), nullable=False, unique=True)  # sha256 hex
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='password_reset_tokens')

