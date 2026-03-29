from app.extensions import db
from datetime import datetime
import uuid

class Email(db.Model):
    __tablename__ = 'emails'
    
    email_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.String(36), db.ForeignKey('posts.post_id', ondelete='CASCADE'), nullable=True)
    profile_id = db.Column(db.String(36), db.ForeignKey('profiles.profile_id'))
    template_id = db.Column(db.String(36), db.ForeignKey('email_templates.template_id', ondelete='SET NULL'), nullable=True)
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)
    recipients = db.Column(db.Text)
    status = db.Column(db.String(50), default='draft')
    approval_status = db.Column(db.String(50), default='pending')  # pending, approved, rejected
    signal_id = db.Column(db.String(36), db.ForeignKey('signals.signal_id', ondelete='SET NULL'), nullable=True)
    message_id = db.Column(db.String(255), nullable=True)  # Message ID from email provider
    sent_at = db.Column(db.DateTime, nullable=True)  # When email was sent
    error_message = db.Column(db.Text, nullable=True)  # Error message if sending failed
    has_reply = db.Column(db.Boolean, default=False)
    reply_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)  # Soft delete timestamp
    
    # Relationships
    template = db.relationship('EmailTemplate', backref='emails')
    post = db.relationship('Post', backref='emails')
    profile = db.relationship('Profile', backref='emails')
    signal = db.relationship('Signal', backref='emails')