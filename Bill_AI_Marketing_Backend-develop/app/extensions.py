from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from celery import Celery

"""
Flask Extensions - Initialized here, configured in app/__init__.py

Why separate file?
- Avoids circular imports
- Extensions need to be created before app, but configured after
- Makes testing easier (can mock extensions)
"""
# Database ORM - Converts Python classes to SQL tables
# Usage: from app.extensions import db


db = SQLAlchemy()

# JWT Authentication - Handles login tokens
# Usage: from app.extensions import jwt

jwt = JWTManager()

# Celery for async tasks
# Usage: from app.extensions import celery

celery = Celery()