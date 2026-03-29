from app.extensions import db
from datetime import datetime
import uuid

class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'
    
    """
    Email Template Model - Reusable email templates with dynamic placeholders.
    
    Templates can be:
    - Default templates (is_default=True) - System templates available to all tenants
    - Custom templates (is_default=False) - User-created templates per tenant
    
    Supported variables:
    - {{recipient_name}}
    - {{company_name}}
    - {{product_name}}
    - {{sender_name}}
    - {{post_summary}}
    
    Attributes:
        template_id (str): Unique identifier (UUID)
        tenant_id (str): Which tenant owns this template (NULL for default templates)
        name (str): Template name (e.g., "Professional Outreach")
        subject (str): Email subject with {{placeholders}}
        body (str): Email body with {{placeholders}}
        is_default (bool): True for system defaults, False for custom templates
        created_at (datetime): When template was created
        updated_at (datetime): When template was last updated
    """
    
    template_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    tenant = db.relationship('Tenant', backref='email_templates')

