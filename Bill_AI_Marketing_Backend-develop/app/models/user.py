from app.extensions import db
from datetime import datetime
import uuid

class User(db.Model):
    __tablename__ = 'users'
    
    """
    User Model - Represents individual users within a tenant.
    
    Users belong to a tenant and can only access their tenant's data.
    Each tenant can have multiple users with different roles.
    
    Attributes:
        user_id (str): Unique identifier (UUID)
        tenant_id (str): Which company this user belongs to
        email (str): User's email (unique across entire system)
        password_hash (str): Bcrypt hashed password (never store plaintext!)
        first_name (str): User's first name
        last_name (str): User's last name
        role (str): User role - 'admin', 'user', 'viewer'
        is_active (bool): Can user login? (for soft delete)
        created_at (datetime): When user registered
    
    Example:
        user = User(
            email="john@microsoft.com",
            tenant_id="tenant-uuid-123",
            role="admin"
        )
    """
    
    user_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.tenant_id', ondelete='CASCADE'), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email_connected = db.Column(db.Boolean, default=False, nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    role = db.Column(db.String(50), default='user')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)