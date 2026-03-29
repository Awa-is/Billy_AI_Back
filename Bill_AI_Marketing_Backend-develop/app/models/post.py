from app.extensions import db
from datetime import datetime
import uuid

class Post(db.Model):
    __tablename__ = 'posts'
    
    post_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    company_id = db.Column(db.String(36), db.ForeignKey('companies.company_id', ondelete='CASCADE'), nullable=False)
    source_url = db.Column(db.Text, nullable=False)
    post_text = db.Column(db.Text)
    post_date = db.Column(db.Date)
    score = db.Column(db.Integer, default=0)
    ai_judgement = db.Column(db.String(50))
    analyzed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)