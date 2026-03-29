"""
Celery entry point for running worker commands.

Usage:
    celery -A celery_worker worker --loglevel=info --pool=solo
    celery -A celery_worker beat --loglevel=info
"""
# Import directly from module to avoid circular imports
import sys
import os

# Add project root to path if needed
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import directly from celery_app module (bypass __init__.py)
from app.tasks.celery_app import celery_app

# IMPORTANT: Import tasks so they're registered with Celery
# This ensures the @celery_app.task decorators are executed
# Import order matters - import celery_app first, then tasks
print("[CELERY WORKER] Importing task modules...")
try:
    from app.tasks import scraper  # noqa: F401
    print("[CELERY WORKER] ✓ scraper module imported")
except Exception as e:
    print(f"[CELERY WORKER] ✗ Failed to import scraper: {e}")
    import traceback
    traceback.print_exc()

try:
    from app.tasks import ai_analyzer  # noqa: F401
    print("[CELERY WORKER] ✓ ai_analyzer module imported")
except Exception as e:
    print(f"[CELERY WORKER] ✗ Failed to import ai_analyzer: {e}")
    import traceback
    traceback.print_exc()

try:
    from app.tasks import email_sender_tasks  # noqa: F401
    print("[CELERY WORKER] ✓ email_sender_tasks module imported")
except Exception as e:
    print(f"[CELERY WORKER] ✗ Failed to import email_sender_tasks: {e}")
    import traceback
    traceback.print_exc()

try:
    from app.tasks import email_tasks  # noqa: F401
    print("[CELERY WORKER] ✓ email_tasks module imported")
except Exception as e:
    print(f"[CELERY WORKER] ✗ Failed to import email_tasks: {e}")
    import traceback
    traceback.print_exc()

try:
    from app.tasks import signal_tasks  # noqa: F401
    print("[CELERY WORKER] ✓ signal_tasks module imported")
except Exception as e:
    print(f"[CELERY WORKER] ✗ Failed to import signal_tasks: {e}")
    import traceback
    traceback.print_exc()

# Verify tasks are registered
print(f"[CELERY WORKER] Registered tasks: {list(celery_app.tasks.keys())}")
print(f"[CELERY WORKER] Total registered tasks: {len(celery_app.tasks)}")

# Check for expected tasks
expected_tasks = ['scrape_company_posts', 'scrape_profiles', 'analyze_post']
for task_name in expected_tasks:
    if task_name in celery_app.tasks:
        print(f"[CELERY WORKER] ✓ Task '{task_name}' is registered")
    else:
        print(f"[CELERY WORKER] ✗ Task '{task_name}' is NOT registered!")

# This makes the celery_app available for command line
if __name__ == '__main__':
    celery_app.start()
