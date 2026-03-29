from app.extensions import db
from datetime import datetime
import uuid

class Signal(db.Model):
    __tablename__ = 'signals'
    
    """
    Signal Model - Represents detected signals from company posts, profile changes, etc.
    
    Signal Types:
    - product_launch: New product announcement
    - company_news: Company news/updates
    - career_move: Person changed companies (from profile updates)
    - linkedin_activity: User's LinkedIn activity/interests
    
    Attributes:
        signal_id (str): Unique identifier (UUID)
        tenant_id (str): Which tenant owns this signal
        signal_type (str): Type of signal (product_launch, company_news, career_move, linkedin_activity)
        post_id (str): Related post (nullable for career_move signals)
        profile_id (str): Related profile (nullable for company post signals)
        company_id (str): Related company
        score (int): AI confidence score (0-100)
        keywords (str): Comma-separated keywords that triggered the signal
        metadata (JSON): Additional signal-specific data
        created_at (datetime): When signal was detected
    """
    
    signal_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    signal_type = db.Column(db.String(50), nullable=False)  # product_launch, company_news, career_move, linkedin_activity
    post_id = db.Column(db.String(36), db.ForeignKey('posts.post_id', ondelete='CASCADE'), nullable=True)
    profile_id = db.Column(db.String(36), db.ForeignKey('profiles.profile_id', ondelete='CASCADE'), nullable=True)
    company_id = db.Column(db.String(36), db.ForeignKey('companies.company_id', ondelete='CASCADE'), nullable=False)
    score = db.Column(db.Integer, nullable=False)  # AI score 0-100
    keywords = db.Column(db.Text, nullable=True)  # Comma-separated keywords
    signal_metadata = db.Column(db.JSON, nullable=True)  # Additional signal data
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    post = db.relationship('Post', backref='signals')
    profile = db.relationship('Profile', backref='signals')
    company = db.relationship('Company', backref='signals')

