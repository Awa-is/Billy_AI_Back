from app.extensions import db
from datetime import datetime
import uuid

class UserSetting(db.Model):
    __tablename__ = 'user_settings'
    
    """
    UserSetting Model - Stores user-specific settings.
    
    Used for AI instructions and other user preferences.
    Each user can have their own settings that persist across sessions.
    
    Attributes:
        setting_id (str): Unique identifier (UUID)
        user_id (str): Foreign key to users.user_id
        key (str): Setting key (e.g., 'ai_email_instructions')
        value (str): Setting value (text)
        created_at (datetime): When setting was created
    """
    
    setting_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='settings')
    
    # Unique constraint: one setting per user per key
    __table_args__ = (
        db.UniqueConstraint('user_id', 'key', name='uq_user_setting_key'),
    )
