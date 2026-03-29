from app.extensions import db
from datetime import datetime
import uuid

class Tenant(db.Model):
    __tablename__ = 'tenants'
    
    """
    Tenant Model - Represents one company/customer using the SaaS.
    
    Each tenant has isolated data. When a tenant is deleted, all their
    data (users, companies, posts, emails) is automatically deleted via CASCADE.
    
    Attributes:
        tenant_id (str): Unique identifier (UUID)
        company_name (str): Company name (e.g., "Microsoft", "Amazon")
        plan (str): Subscription plan - 'free', 'pro', 'enterprise'
        status (str): Account status - 'active', 'suspended', 'cancelled'
        created_at (datetime): When tenant was created
    """

    tenant_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_name = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.String(50), default='free')
    status = db.Column(db.String(50), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - CASCADE means deleting tenant deletes all related data
    users = db.relationship('User', backref='tenant', cascade='all, delete-orphan')
    companies = db.relationship('Company', backref='tenant', cascade='all, delete-orphan')