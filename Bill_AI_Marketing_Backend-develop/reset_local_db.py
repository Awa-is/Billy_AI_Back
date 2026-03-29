
from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Dropping all tables...")
    # Reflect metadata to drop all
    db.reflect()
    db.drop_all()
    # Also drop alembic_version table manually if it exists
    try:
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
        db.session.commit()
    except Exception as e:
        print(f"Error dropping alembic table: {e}")
    print("All tables dropped.")
