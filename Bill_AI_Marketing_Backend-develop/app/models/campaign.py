from app.extensions import db
from datetime import datetime
import uuid


class Campaign(db.Model):
    __tablename__ = 'campaigns'

    """
    Campaign Model - links a product launch post with multiple profiles.
    Tracks rollout status so users know whether the outreach is drafted,
    running, or completed.
    """

    campaign_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    post_id = db.Column(db.String(36), db.ForeignKey('posts.post_id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = db.relationship('Tenant', backref='campaigns')
    post = db.relationship('Post', backref='campaigns')
    campaign_profiles = db.relationship('CampaignProfile', backref='campaign', cascade='all, delete-orphan')


class CampaignProfile(db.Model):
    __tablename__ = 'campaign_profiles'

    """
    Junction table linking campaigns to profiles and tracking per-profile
    outreach status + generated email linkage.
    """

    campaign_id = db.Column(db.String(36), db.ForeignKey('campaigns.campaign_id', ondelete='CASCADE'), primary_key=True)
    profile_id = db.Column(db.String(36), db.ForeignKey('profiles.profile_id', ondelete='CASCADE'), primary_key=True)
    status = db.Column(db.String(50), nullable=False, default='pending')
    email_id = db.Column(db.String(36), db.ForeignKey('emails.email_id', ondelete='SET NULL'), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    profile = db.relationship('Profile', backref='campaign_profiles')
    email = db.relationship('Email', backref='campaign_profiles')


