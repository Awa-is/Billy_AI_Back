#!/bin/bash
# Startup script for Render deployment
# Runs both Flask (Gunicorn) and Celery worker in the same service

set -e

echo "Running database migrations (startup backup)..."
python run_migrations.py || echo "Warning: Migrations may have already run during build"

# Function to cleanup Celery on exit
cleanup() {
    echo "Shutting down Celery worker..."
    if [ -f /tmp/celery.pid ]; then
        kill $(cat /tmp/celery.pid) 2>/dev/null || true
        rm -f /tmp/celery.pid
    fi
    exit 0
}

# Trap signals to cleanup Celery
trap cleanup SIGTERM SIGINT

echo "Starting Celery worker in background..."
celery -A celery_worker worker --loglevel=info --pool=solo --pidfile=/tmp/celery.pid --logfile=/tmp/celery.log &
CELERY_PID=$!

# Wait a moment to ensure Celery started
sleep 2

# Check if Celery is still running
if ! kill -0 $CELERY_PID 2>/dev/null; then
    echo "ERROR: Celery worker failed to start!"
    exit 1
fi

echo "Celery worker started with PID: $CELERY_PID"
echo "Starting Gunicorn server..."

# Start Gunicorn as main process (Render monitors this)
# When Gunicorn exits, the cleanup function will kill Celery
exec gunicorn --bind 0.0.0.0:$PORT wsgi:app

