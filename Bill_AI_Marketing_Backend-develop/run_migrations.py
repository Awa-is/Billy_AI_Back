#!/usr/bin/env python
"""
Script to run database migrations before starting the server.
This ensures migrations run with proper Flask app context.
"""
import sys
import os

# Note: Set PYTHONUNBUFFERED=1 in environment for unbuffered output

print("=" * 60)
print("DATABASE MIGRATION SCRIPT STARTING")
print("=" * 60)

# Check if DATABASE_URL is set
db_url = os.getenv('DATABASE_URL')
if not db_url:
    print("ERROR: DATABASE_URL environment variable is not set!")
    print("Available environment variables:")
    for key in sorted(os.environ.keys()):
        if 'DATABASE' in key or 'DB' in key:
            print(f"  {key} = {os.environ[key][:50]}...")
    sys.exit(1)

print(f"✓ DATABASE_URL is set")
print(f"  Database: {db_url.split('/')[-1] if '/' in db_url else 'unknown'}")
print(f"  Host: {db_url.split('@')[1].split('/')[0] if '@' in db_url else 'unknown'}")

try:
    print("\n" + "=" * 60)
    print("Creating Flask app...")
    print("=" * 60)
    from app import create_app
    app = create_app()
    print("✓ Flask app created successfully")
    
    print("\n" + "=" * 60)
    print("Creating Flask app context...")
    print("=" * 60)
    with app.app_context():
        print("✓ Flask app context created")
        
        # Test database connection
        print("\n" + "=" * 60)
        print("Testing database connection...")
        print("=" * 60)
        from app.extensions import db
        try:
            db.engine.connect()
            print("✓ Database connection successful")
        except Exception as conn_error:
            print(f"✗ Database connection failed: {conn_error}")
            raise
        
        print("\n" + "=" * 60)
        print("Running database migrations...")
        print("=" * 60)
        from flask_migrate import upgrade, current
        try:
            # Check current migration version
            try:
                current_rev = current()
                print(f"Current migration version: {current_rev}")
            except Exception:
                print("No migration version found - this is a fresh database")
            
            # Run migrations
            upgrade()
            print("\n" + "=" * 60)
            print("✓ Migrations completed successfully!")
            print("=" * 60)
        except Exception as migration_error:
            print("\n" + "=" * 60)
            print(f"✗ Migration error: {migration_error}")
            print("=" * 60)
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
except ImportError as import_error:
    print(f"\n✗ Import error: {import_error}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f"\n✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("MIGRATION SCRIPT COMPLETED SUCCESSFULLY")
print("=" * 60)

