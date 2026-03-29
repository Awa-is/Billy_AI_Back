from celery import Celery
from dotenv import load_dotenv
import os
import sys
from pathlib import Path

# Load environment variables - use absolute path to .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Also try loading from current directory
load_dotenv()

# Get Redis URL - check multiple environment variables with proper fallback
# Priority: REDIS_URL > CELERY_BROKER_URL > CELERY_RESULT_BACKEND
# This handles cases where Render might set different variable names
redis_url = (
    os.getenv('REDIS_URL') or 
    os.getenv('CELERY_BROKER_URL') or 
    os.getenv('CELERY_RESULT_BACKEND') or
    None
)

# Validate Redis URL
if not redis_url or not isinstance(redis_url, str) or not redis_url.strip():
    # Fallback to localhost only in development
    redis_url = 'redis://localhost:6379/0'
    print(f"[CELERY CONFIG] WARNING: No Redis URL found in environment, using fallback: {redis_url}")
elif not redis_url.startswith('redis://'):
    print(f"[CELERY CONFIG] WARNING: Redis URL doesn't start with 'redis://': {redis_url}")
    # Try to fix common issues
    if redis_url.startswith('rediss://'):
        redis_url = redis_url.replace('rediss://', 'redis://', 1)
    else:
        redis_url = f'redis://{redis_url}'

# Strip any whitespace
redis_url = redis_url.strip()

print(f"[CELERY CONFIG] Using broker: {redis_url}")  # Debug output
print(f"[CELERY CONFIG] REDIS_URL from env: {os.getenv('REDIS_URL')}")  # Debug
print(f"[CELERY CONFIG] CELERY_BROKER_URL from env: {os.getenv('CELERY_BROKER_URL')}")  # Debug
print(f"[CELERY CONFIG] CELERY_RESULT_BACKEND from env: {os.getenv('CELERY_RESULT_BACKEND')}")  # Debug

# Final validation - ensure we have a valid Redis URL
if not redis_url or redis_url == 'redis://localhost:6379/0':
    import warnings
    warnings.warn(
        f"Celery is using fallback Redis URL: {redis_url}. "
        "Make sure REDIS_URL, CELERY_BROKER_URL, or CELERY_RESULT_BACKEND is set in environment variables."
    )

# Detect Windows and set appropriate pool
is_windows = sys.platform.startswith('win')
pool_type = 'solo' if is_windows else 'prefork'
print(f"[CELERY CONFIG] Using pool: {pool_type} (Windows: {is_windows})")  # Debug output

# Create Celery instance with Redis - SET BROKER IN CONSTRUCTOR
# Ensure broker and backend are explicitly set and not None
try:
    celery_app = Celery(
        'billy_ai',
        broker=redis_url,  # Set broker directly in constructor
        backend=redis_url  # Set backend directly in constructor
    )
except Exception as e:
    raise RuntimeError(
        f"Failed to initialize Celery with Redis URL '{redis_url}': {str(e)}. "
        "Please check your REDIS_URL environment variable."
    ) from e

# Update configuration - ensure Redis transport
celery_app.conf.update(
    broker_url=redis_url,  # Explicitly set again
    result_backend=redis_url,  # Explicitly set again
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    broker_connection_retry_on_startup=True,
    worker_pool=pool_type,
    broker_transport='redis',  # Force Redis transport
    broker_transport_options={
        'visibility_timeout': 3600,
        'retry_policy': {
            'timeout': 5.0
        }
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(['app.tasks'])

# Note: We don't explicitly import tasks here to avoid circular imports.
# The autodiscover_tasks() call will automatically discover and register
# all tasks decorated with @celery_app.task in the app.tasks package.
# Tasks are imported lazily when needed, which prevents circular import issues.

# Final verification - ensure broker is properly configured
final_broker = celery_app.conf.broker_url
final_backend = celery_app.conf.result_backend

if not final_broker or final_broker == 'memory://':
    raise RuntimeError(
        f"Celery broker_url is not properly configured. Got: {final_broker}. "
        "Please set REDIS_URL, CELERY_BROKER_URL, or CELERY_RESULT_BACKEND environment variable."
    )

if not final_backend or final_backend == 'memory://':
    raise RuntimeError(
        f"Celery result_backend is not properly configured. Got: {final_backend}. "
        "Please set REDIS_URL, CELERY_BROKER_URL, or CELERY_RESULT_BACKEND environment variable."
    )

print(f"[CELERY CONFIG] Final broker_url: {final_broker}")
print(f"[CELERY CONFIG] Final result_backend: {final_backend}")
print(f"[CELERY CONFIG] Registered tasks: {list(celery_app.tasks.keys())}")

