from app.extensions import db
from datetime import datetime
import uuid


class TransactionalEmailTemplate(db.Model):
    __tablename__ = 'transactional_email_templates'

    template_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=True)

    # Stable identifier for API usage, e.g. "password_reset"
    key = db.Column(db.String(100), nullable=False)

    name = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(250), nullable=False)
    body = db.Column(db.Text, nullable=False)

    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tenant = db.relationship('Tenant', backref='transactional_email_templates')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'key', name='uq_transactional_template_tenant_key'),
    )

