"""
Attachment Model

Stores metadata for file attachments uploaded by users.
Files are stored on disk (or cloud storage) and referenced by ID.
"""

from app.extensions import db
from datetime import datetime
import uuid
import os

class Attachment(db.Model):
    __tablename__ = 'attachments'
    
    """
    Attachment Model - Stores file attachment metadata.
    
    Files are uploaded via POST /attachments and referenced by ID when sending emails.
    This follows a two-step process:
    1. Upload file → Get attachment ID
    2. Reference ID when sending email
    
    Attributes:
        attachment_id (str): Unique identifier (UUID)
        tenant_id (str): Foreign key to tenants.tenant_id
        user_id (str): Foreign key to users.user_id (who uploaded it)
        filename (str): Original filename
        file_path (str): Path to stored file on disk/cloud
        file_size (int): File size in bytes
        content_type (str): MIME type (e.g., 'application/pdf')
        created_at (datetime): When attachment was uploaded
        deleted_at (datetime): Soft delete timestamp (null if not deleted)
    """
    
    attachment_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)  # Path to stored file
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    content_type = db.Column(db.String(100), nullable=False)  # MIME type
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)  # Soft delete
    expires_at = db.Column(db.DateTime, nullable=True)  # Expiration time (24 hours from upload if not attached to email)
    is_permanent = db.Column(db.Boolean, default=False, nullable=False)  # True if attached to a sent email
    
    # Relationships
    tenant = db.relationship('Tenant', backref='attachments')
    user = db.relationship('User', backref='attachments')
    
    def to_dict(self):
        """Convert attachment to dictionary for API responses."""
        return {
            "id": self.attachment_id,
            "filename": self.filename,
            "size": self.file_size,
            "mimeType": self.content_type,
            "uploadedAt": self.created_at.isoformat() if self.created_at else None,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None
        }
    
    def is_deleted(self):
        """Check if attachment is soft-deleted."""
        return self.deleted_at is not None
    
    def get_file_path(self):
        """Get full path to the stored file."""
        return self.file_path
