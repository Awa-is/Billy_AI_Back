from app.extensions import db
from datetime import datetime
import uuid


class TokenBlocklist(db.Model):
    __tablename__ = 'token_blocklist'

    block_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    jti = db.Column(db.String(36), nullable=False, unique=True)
    token_type = db.Column(db.String(20), nullable=False)  # access / refresh
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

