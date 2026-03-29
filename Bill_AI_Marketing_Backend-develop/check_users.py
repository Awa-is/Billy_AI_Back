from app import create_app
from app.models.user import User

app = create_app()

with app.app_context():
    count = User.query.count()
    print(f"Total Users in DB: {count}")
    
    users = User.query.all()
    for u in users:
        print(f" - Found User: {u.email}")
