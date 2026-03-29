from app.extensions import db
from datetime import datetime
import uuid

class UserEmailProvider(db.Model):
    __tablename__ = 'user_email_providers'
    
    """
    UserEmailProvider Model - Stores OAuth credentials for user email accounts.
    
    Allows users to connect their Microsoft or Google email accounts via OAuth
    so they can send emails from their own email addresses instead of a shared
    AWS SES sender.
    
    Attributes:
        provider_id (str): Unique identifier (UUID)
        user_id (str): Foreign key to users.user_id
        email (str): User's email address
        provider (str): 'microsoft' or 'google'
        access_token (str): Encrypted OAuth access token
        refresh_token (str): Encrypted OAuth refresh token (nullable)
        token_expires_at (datetime): When access token expires (nullable)
        provider_data (dict): JSON field for provider-specific user info
        is_active (bool): Whether this provider connection is active
        created_at (datetime): When connection was created
        updated_at (datetime): When connection was last updated
    
    Constraints:
        - Unique constraint on (user_id, email, provider)
        - Cascade delete when user is deleted
    """
    
    provider_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    provider = db.Column(db.String(50), nullable=False)  # 'microsoft' or 'google'
    access_token = db.Column(db.Text, nullable=True)  # Encrypted OAuth access token
    refresh_token = db.Column(db.Text, nullable=True)  # Encrypted OAuth refresh token
    token_expires_at = db.Column(db.DateTime, nullable=True)  # When access token expires
    provider_data = db.Column(db.JSON, nullable=True)  # Store provider-specific user info
    email_connected = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='email_providers')
    
    # Unique constraint on (user_id, email, provider)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'email', 'provider', name='uq_user_email_provider'),
    )
    
    def __repr__(self):
        return f'<UserEmailProvider {self.provider_id} {self.provider} {self.email}>'
    
    def to_dict(self):
        """Convert model to dictionary for API responses."""
        return {
            'provider_id': self.provider_id,
            'user_id': self.user_id,
            'email': self.email,
            'provider': self.provider,
            'email_connected': self.email_connected,
            'is_active': self.is_active,
            'token_expires_at': self.token_expires_at.isoformat() if self.token_expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

