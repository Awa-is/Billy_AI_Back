# Billy AI Marketing Backend

Flask backend for LinkedIn Product Launch detection and email outreach automation.

## Architecture

- **Backend:** Flask (Python)
- **Database:** PostgreSQL (multi-tenant)
- **Cache/Queue:** Redis + Celery
- **Frontend:** React (separate repo)
- **Deployment:** AWS ECS

## Tech Stack

- Flask 3.0 - Web framework
- SQLAlchemy - ORM
- PostgreSQL - Database
- Redis - Cache & task queue
- Celery - Async tasks
- JWT - Authentication
- Docker - Local development

## Quick Start

### Prerequisites

- Python 3.11+
- Docker Desktop
- Git

### Setup
```bash
# 1. Clone repo
git clone https://github.com/usamaabbasi135/Bill_AI_Marketing_Backend
cd billy-ai-backend

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment file
cp .env.example .env

# 5. Start database (Docker)
docker-compose up -d

# 6. Run migrations
flask db upgrade

# 7. Start server
python run.py
```

Server runs at: http://localhost:5000

## Project Structure
```
billy-ai-backend/
├── app/
│   ├── __init__.py          # App factory
│   ├── config.py            # Configuration
│   ├── extensions.py        # Flask extensions
│   ├── models/              # Database models
│   │   ├── tenant.py        # Tenant (company)
│   │   ├── user.py          # Users
│   │   ├── company.py       # LinkedIn companies to track
│   │   ├── post.py          # LinkedIn posts
│   │   ├── profile.py       # LinkedIn profiles
│   │   ├── email.py         # Generated emails
│   │   └── tenant_setting.py # Settings per tenant
│   ├── api/                 # API endpoints
│   ├── services/            # Business logic
│   └── tasks/               # Celery async tasks
├── migrations/              # Database migrations
├── tests/                   # Tests
├── docker-compose.yml       # Local dev services
├── requirements.txt         # Python dependencies
├── run.py                   # App entry point
└── .env                     # Environment variables (not in git)
```

## Database Schema

### Multi-Tenant Architecture

Each tenant (company) has isolated data:
```
tenants (1) ─┬─→ users (many)
             ├─→ companies (many)
             ├─→ posts (many)
             ├─→ profiles (many)
             ├─→ emails (many)
             └─→ tenant_settings (many)
```

All tables have `tenant_id` foreign key with `ON DELETE CASCADE`.

## Authentication

JWT-based authentication:

1. User registers → Creates tenant + user
2. User logs in → Returns JWT token
3. Frontend includes token in all requests
4. Backend validates token and extracts tenant_id

## Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_auth.py

# Run with coverage
pytest --cov=app
```

## Git Workflow

### Branch Strategy

- `main` - Production
- `develop` - Staging
- `feature/*` - New features

### Working on Issues
```bash
# 1. Create branch from develop
git checkout develop
git pull origin develop
git checkout -b feature/user-registration

# 2. Code and commit
git add .
git commit -m "feat: add user registration endpoint (#3)"

# 3. Push and create PR
git push origin feature/user-registration
```

## Environment Variables
```bash
# Database
DATABASE_URL=postgresql://dev:dev123@localhost:5432/billy_ai

# Redis
REDIS_URL=redis://localhost:6379/0

# Security (generate with: python -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET_KEY=your-jwt-secret-here
SECRET_KEY=your-flask-secret-here

# APIs (get from respective platforms)
APIFY_API_TOKEN=your-apify-token
CLAUDE_API_KEY=your-claude-key
```

## API Documentation

## API Documentation

**Full API Docs:** [docs/API.md](docs/API.md)

**Quick Test:**
```bash
# Health check
curl http://localhost:5000/api/health

# Register user
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"Test1234","first_name":"Test","last_name":"User","company_name":"Test Co"}'

# Create company (replace <ACCESS_TOKEN>)
curl -X POST http://localhost:5000/api/companies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -d '{"name":"OpenAI","linkedin_url":"https://www.linkedin.com/company/openai/"}'
```

**For Frontend Developers:**
- Base URL: `http://localhost:5000`
- API Docs: See [docs/API.md](docs/API.md)
- Postman Collection: [postman/Billy_AI_API.postman_collection.json](postman/Billy_AI_API.postman_collection.json)

## Authentication

All protected endpoints require JWT token:
```javascript
headers: {
  'Authorization': 'Bearer ' + access_token
}
```

## Troubleshooting

**Database connection error:**
```bash
# Restart Docker containers
docker-compose down
docker-compose up -d
```

**Migration errors:**
```bash
# Reset database (WARNING: deletes all data)
docker-compose down -v
docker-compose up -d
flask db upgrade
```

## Team

- Backend Lead: usama abbasi & Hamza
- Frontend Developer: Saqib U llah

## 📄 License

Private - Not for public use

