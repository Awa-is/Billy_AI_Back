import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    # Database - Render provides this as DATABASE_URL
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    
    # Fix for Render's postgres:// vs postgresql://
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Redis / Celery
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)

    # Claude / Anthropic
    CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')
    # Support comma-separated list of models for fallback
    # Updated to use available 4.5 models: Opus 4.5, Sonnet 4.5, Haiku 4.5
    # Model names use simplified format: claude-{model}-{version}
    _claude_models = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-5,claude-opus-4-5,claude-haiku-4-5,claude-3-5-opus-20241022,claude-3-5-haiku-20241022')
    CLAUDE_MODELS = [m.strip() for m in _claude_models.split(',')]
    CLAUDE_MODEL = CLAUDE_MODELS[0]  # Default to first model for backward compatibility
    CLAUDE_MAX_TOKENS = int(os.getenv('CLAUDE_MAX_TOKENS', '800'))
     # Apify Configuration
    APIFY_API_TOKEN = os.getenv('APIFY_API_TOKEN')
    APIFY_ACTOR_ID = 'bestscrapers/linkedin-company-post-scraper'  # Updated from apimaestro (had bug returning wrong company posts)
    
    APIFY_PROFILE_ACTOR_ID = os.getenv('APIFY_PROFILE_ACTOR_ID', 'dev_fusion/linkedin-profile-scraper')
    # AWS SES Configuration
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    SES_SENDER_EMAIL = os.getenv('SES_SENDER_EMAIL')
    
    # Microsoft OAuth Configuration
    MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID')
    MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET')
    MICROSOFT_REDIRECT_URI = os.getenv('MICROSOFT_REDIRECT_URI', 'http://localhost:5000/api/auth/oauth/microsoft/callback')
    MICROSOFT_SCOPES = 'https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access'
    
    # Google OAuth Configuration
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/api/auth/oauth/google/callback')
    GOOGLE_SCOPES = 'https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email'

    # Password reset
    FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', 'http://localhost:8080')
    PASSWORD_RESET_URL = os.getenv('PASSWORD_RESET_URL')  # Optional override
    PASSWORD_RESET_TOKEN_EXPIRES_MINUTES = int(os.getenv('PASSWORD_RESET_TOKEN_EXPIRES_MINUTES', '60'))