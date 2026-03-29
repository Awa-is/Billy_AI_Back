from app.extensions import db
from datetime import datetime
import uuid

class Company(db.Model):
    __tablename__ = 'companies'
    
    """
    Company Model - LinkedIn companies that a tenant wants to track.
    
    Each tenant can track multiple companies. We scrape these companies'
    LinkedIn posts to detect product launches.
    
    Attributes:
        company_id (str): Unique identifier (UUID)
        tenant_id (str): Which tenant is tracking this company
        name (str): Company name (e.g., "Google", "Apple")
        linkedin_url (str): LinkedIn company page URL
        is_active (bool): Should we still scrape this company?
        created_at (datetime): When company was added
    
    Example:
        company = Company(
            name="Google",
            linkedin_url="https://linkedin.com/company/google",
            tenant_id="tenant-uuid-123"
        )
    """
    
    company_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    linkedin_url = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    last_scraped_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    posts = db.relationship('Post', backref='company', cascade='all, delete-orphan')