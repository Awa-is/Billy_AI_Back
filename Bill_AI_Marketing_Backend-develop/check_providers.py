
from app import create_app
from app.extensions import db
from app.models.user_email_provider import UserEmailProvider
from app.models.user import User
from app.models.tenant import Tenant

app = create_app()

with app.app_context():
    print("Checking UserEmailProviders...")
    providers = UserEmailProvider.query.all()
    for p in providers:
        print(f"Provider: {p.provider}, UserID: {p.user_id}, Active: {p.is_active}, Email: {p.email}")
    
    if not providers:
        print("No UserEmailProviders found!")

    print("\nChecking Users...")
    users = User.query.all()
    for u in users:
        print(f"User: {u.first_name} {u.last_name}, ID: {u.user_id}, Tenant: {u.tenant_id}")
