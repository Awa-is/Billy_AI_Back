from app.extensions import db
from datetime import datetime
import uuid

class TenantSetting(db.Model):
    __tablename__ = 'tenant_settings'
    
    setting_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)