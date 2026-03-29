from app.extensions import db
from datetime import datetime
import uuid
import json

class Profile(db.Model):
    __tablename__ = 'profiles'
    
    profile_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    person_name = db.Column(db.String(255))
    headline = db.Column(db.Text)
    linkedin_url = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='url_only')
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    company = db.Column(db.String(255))
    job_title = db.Column(db.String(255))
    location = db.Column(db.String(255))
    industry = db.Column(db.String(255))
    scraped_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New fields from dev_fusion/linkedin-profile-scraper
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    full_name = db.Column(db.String(255))
    connections = db.Column(db.Integer)
    followers = db.Column(db.Integer)
    mobile_number = db.Column(db.String(50))
    job_started_on = db.Column(db.String(50))
    job_location = db.Column(db.String(255))
    job_still_working = db.Column(db.Boolean)
    company_name = db.Column(db.String(255))
    company_industry = db.Column(db.String(255))
    company_website = db.Column(db.Text)
    company_linkedin = db.Column(db.Text)
    company_founded_in = db.Column(db.String(50))
    company_size = db.Column(db.String(100))
    address_country_only = db.Column(db.String(255))
    address_with_country = db.Column(db.String(255))
    address_without_country = db.Column(db.String(255))
    profile_pic = db.Column(db.Text)
    profile_pic_high_quality = db.Column(db.Text)
    background_pic = db.Column(db.Text)
    linkedin_id = db.Column(db.String(100))
    public_identifier = db.Column(db.String(255))
    linkedin_public_url = db.Column(db.Text)
    urn = db.Column(db.String(255))
    is_premium = db.Column(db.Boolean)
    is_verified = db.Column(db.Boolean)
    is_job_seeker = db.Column(db.Boolean)
    is_retired = db.Column(db.Boolean)
    is_creator = db.Column(db.Boolean)
    is_influencer = db.Column(db.Boolean)
    about = db.Column(db.Text)
    experiences = db.Column(db.Text)  # JSON string
    skills = db.Column(db.Text)  # JSON string
    educations = db.Column(db.Text)  # JSON string

    # Template preference for email generation
    assigned_template_id = db.Column(db.String(36), db.ForeignKey('email_templates.template_id', ondelete='SET NULL'), nullable=True)
    assigned_template = db.relationship('EmailTemplate', foreign_keys=[assigned_template_id])