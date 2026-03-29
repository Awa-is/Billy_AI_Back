# How to Run the Application Locally

## Prerequisites
- Python 3.11+ installed
- Docker Desktop running (for PostgreSQL and Redis)
- Virtual environment created

## Step-by-Step Instructions

### Step 1: Start Docker Services
Make sure PostgreSQL and Redis are running:
```powershell
docker-compose up -d
```

Verify they're running:
```powershell
docker ps
```
You should see `billy_ai_postgres` and `linkedin_redis` containers.

---

### Step 2: Open Terminal 1 - Flask Server

1. **Navigate to project directory:**
   ```powershell
   cd "U:\Usama\Projects\Billy AI Marketing Backend"
   ```

2. **Activate virtual environment:**
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   You should see `(venv)` in your prompt.

3. **Run database migrations (if needed):**
   ```powershell
   flask db upgrade
   ```

4. **Start Flask server:**
   ```powershell
   python run.py
   ```

5. **Verify it's running:**
   - You should see: `Running on http://127.0.0.1:5000`
   - Open browser: http://localhost:5000/api/health
   - Should return: `{"status": "ok"}`

**Keep this terminal open!** The Flask server must stay running.

---

### Step 3: Open Terminal 2 - Celery Worker

1. **Open a NEW terminal/PowerShell window**

2. **Navigate to project directory:**
   ```powershell
   cd "U:\Usama\Projects\Billy AI Marketing Backend"
   ```

3. **Activate virtual environment:**
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   You should see `(venv)` in your prompt.

4. **Start Celery worker:**
   ```powershell
   celery -A celery_worker worker --loglevel=info --pool=solo
   ```

5. **Verify it's running:**
   - You should see: `celery@hostname ready.`
   - You should see registered tasks like: `scrape_profiles`, `scrape_company_posts`, etc.

**Keep this terminal open!** The Celery worker must stay running.

---

## Summary

You need **TWO terminals running simultaneously**:

### Terminal 1 (Flask Server):
```powershell
cd "U:\Usama\Projects\Billy AI Marketing Backend"
.\venv\Scripts\Activate.ps1
python run.py
```

### Terminal 2 (Celery Worker):
```powershell
cd "U:\Usama\Projects\Billy AI Marketing Backend"
.\venv\Scripts\Activate.ps1
celery -A celery_worker worker --loglevel=info --pool=solo
```

---

## Testing the Application

### 1. Health Check
```powershell
curl http://localhost:5000/api/health
```
Should return: `{"status": "ok"}`

### 2. Test Profile Scraping
1. Register/Login to get JWT token
2. Add a profile: `POST /api/profiles` with `{"linkedin_url": "https://www.linkedin.com/in/williamhgates"}`
3. Scrape the profile: `POST /api/profiles/{profile_id}/scrape`
4. Check Celery worker terminal - you should see task execution
5. List profiles: `GET /api/profiles` - should show all new fields

---

## Troubleshooting

### Flask server won't start:
- Check if port 5000 is already in use
- Verify virtual environment is activated
- Check for import errors in the terminal

### Celery worker won't start:
- Verify Redis is running: `docker ps`
- Check Redis connection: `redis-cli ping` (should return PONG)
- Make sure virtual environment is activated

### Tasks not executing:
- Verify both Flask server AND Celery worker are running
- Check that both are using the same Redis instance
- Look for errors in Celery worker terminal

### Database errors:
- Verify PostgreSQL is running: `docker ps`
- Run migrations: `flask db upgrade`
- Check DATABASE_URL in environment variables

---

## Quick Start Script (Optional)

You can create a batch file to start both services:

**start-dev.bat:**
```batch
@echo off
start "Flask Server" cmd /k "cd /d U:\Usama\Projects\Billy AI Marketing Backend && venv\Scripts\activate && python run.py"
timeout /t 3
start "Celery Worker" cmd /k "cd /d U:\Usama\Projects\Billy AI Marketing Backend && venv\Scripts\activate && celery -A celery_worker worker --loglevel=info --pool=solo"
```

Then just run: `start-dev.bat`

