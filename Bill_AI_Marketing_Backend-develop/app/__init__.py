import os
from flask import Flask, jsonify
from flask_cors import CORS
from flask_migrate import Migrate
from app.config import Config
from app.extensions import db, jwt
from app.celery_app import init_celery
from app.models.token_blocklist import TokenBlocklist

migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)
    CORS(app)
    
    # Health check endpoint - register early so it's always available
    @app.route('/api/health', methods=['GET'])
    def health():
        return jsonify({"status": "ok"}), 200
    
    # Import models
    from app.models import (
        Tenant,
        User,
        Company,
        Post,
        Profile,
        Email,
        TenantSetting,
        EmailTemplate,
        Campaign,
        CampaignProfile,
        Job,
        UserEmailProvider,
        Signal,
        UserSetting,
    )
    
    # Register blueprints
    from app.api import auth
    app.register_blueprint(auth.bp, url_prefix='/api/auth')
    from app.api import companies
    app.register_blueprint(companies.bp, url_prefix='/api/companies')
    from app.api import posts
    app.register_blueprint(posts.bp, url_prefix='/api/posts')
    from app.api import templates
    app.register_blueprint(templates.bp, url_prefix='/api/templates')
    from app.api import campaigns
    app.register_blueprint(campaigns.bp, url_prefix='/api/campaigns')
    from app.api import emails
    app.register_blueprint(emails.bp, url_prefix='/api/emails')
    try:
        from app.api import transactional_emails
        app.register_blueprint(transactional_emails.bp, url_prefix='/api/transactional-emails')
    except ImportError:
        pass
    from app.api import contacts
    app.register_blueprint(contacts.bp, url_prefix='/api/contacts')
    from app.api import signals
    app.register_blueprint(signals.bp, url_prefix='/api/signals')
    from app.api import oauth
    app.register_blueprint(oauth.bp, url_prefix='/api/auth/oauth')
    # Register profiles blueprint if it exists
    try:
        from app.api import profiles
        app.register_blueprint(profiles.bp, url_prefix='/api/profiles')
    except ImportError:
        pass  # profiles module doesn't exist yet
    # Register jobs blueprint if it exists
    try:
        from app.api import jobs
        app.register_blueprint(jobs.bp, url_prefix='/api/jobs')
    except ImportError:
        pass  # jobs module doesn't exist yet
        
    # Register pipeline blueprint
        pass
        
    # Register pipeline blueprint
    try:
        from app.api import pipeline
        app.register_blueprint(pipeline.bp, url_prefix='/api/pipeline')
    except ImportError:
        pass

    # Register conversations blueprint
    try:
        from app.api import conversations
        app.register_blueprint(conversations.bp, url_prefix='/api/conversations')
    except ImportError:
        pass

    # Register ai blueprint
    try:
        from app.api import ai
        app.register_blueprint(ai.bp, url_prefix='/api/ai')
    except ImportError:
        pass

    # Register aiinstructions blueprint
    try:
        from app.api import aiinstructions
        app.register_blueprint(aiinstructions.bp, url_prefix='/api/ai-instructions')
    except ImportError:
        pass

    # JWT error handlers for clearer responses
    @jwt.unauthorized_loader
    def jwt_missing_token(err):
        return jsonify({"error": "Unauthorized", "details": err}), 401

    @jwt.invalid_token_loader
    def jwt_invalid_token(err):
        return jsonify({"error": "Invalid token", "details": err}), 401

    @jwt.expired_token_loader
    def jwt_expired_token(header, payload):
        return jsonify({"error": "Token expired"}), 401

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload.get("jti")
        if not jti:
            return False
        return TokenBlocklist.query.filter_by(jti=jti).first() is not None
    
    init_celery(app)
    
    return app