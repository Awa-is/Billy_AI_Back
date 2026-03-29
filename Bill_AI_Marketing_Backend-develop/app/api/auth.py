from flask import Blueprint, request, jsonify, current_app
from marshmallow import ValidationError
from flask_jwt_extended import create_access_token, create_refresh_token
from app.extensions import db
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_email_provider import UserEmailProvider
from app.schemas.auth_schema import RegisterSchema, UserResponseSchema, TenantResponseSchema
from app.services.password_service import hash_password, verify_password
from app.services.password_reset_service import create_reset_token, find_valid_token, mark_token_used
from app.services.transactional_email import send_transactional_email
from app.config import Config
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from datetime import datetime, timezone
from app.models.token_blocklist import TokenBlocklist

# Create Blueprint
bp = Blueprint('auth', __name__)

# Initialize schemas
register_schema = RegisterSchema()
user_schema = UserResponseSchema()
tenant_schema = TenantResponseSchema()


@bp.route('/register', methods=['POST'])
def register():
    """User Registration Endpoint"""

    """
    User Registration Endpoint
    
    Creates a new tenant and admin user in one transaction.
    First user in a tenant is always assigned 'admin' role.
    
    Request Body:
        {
            "email": "user@example.com",
            "password": "SecurePass123",
            "first_name": "John",
            "last_name": "Doe",
            "company_name": "Acme Inc"
        }
    
    Returns:
        201: Registration successful with JWT tokens
        400: Validation error or email already exists
        500: Server error
    
    Example:
        POST /api/auth/register
        {
            "email": "john@acme.com",
            "password": "SecurePass123",
            "first_name": "John",
            "last_name": "Doe",
            "company_name": "Acme Inc"
        }
        
        Response:
        {
            "message": "Registration successful",
            "user": {...},
            "tenant": {...},
            "access_token": "eyJhbGc...",
            "refresh_token": "eyJhbGc..."
        }
    """
    try:
        # Step 1: Get and validate data
        data = request.get_json()
        
        try:
            validated_data = register_schema.load(data)
        except ValidationError as err:
            return jsonify({"error": "Validation failed", "details": err.messages}), 400
        
        # Step 2: Check if email already registered
        if User.query.filter_by(email=validated_data['email']).first():
            return jsonify({"error": "Email already registered"}), 400
        
        # Step 3: Create new tenant
        tenant = Tenant(
            company_name=validated_data['company_name'],
            plan='free',
            status='active'
        )
        
        # Step 4: Add and flush to generate tenant_id
        db.session.add(tenant)
        db.session.flush()  # Generates UUID without committing
        
        # Step 5: Hash password
        password_hash = hash_password(validated_data['password'])
        
        # Step 6: Create admin user with tenant_id
        user = User(
            email=validated_data['email'],
            password_hash=password_hash,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            tenant_id=tenant.tenant_id,  # Now has value
            role='admin',
            is_active=True
        )
        
        # Step 7: Save user and commit transaction
        db.session.add(user)
        db.session.commit()
        
        # Step 8: Generate JWT tokens
        access_token = create_access_token(
            identity=user.user_id,
            additional_claims={
                "tenant_id": user.tenant_id,
                "email": user.email,
                "role": user.role
            }
        )
        
        refresh_token = create_refresh_token(identity=user.user_id)
        
        # Step 9: Return minimal response (no tenant_id exposure)
        safe_user = {
            "user_id": user.user_id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "email_connected": bool(getattr(user, "email_connected", False)),
        }

        return jsonify({
            "message": "Registration successful",
            "user": safe_user,
            "access_token": access_token,
            "refresh_token": refresh_token
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


@bp.route('/login', methods=['POST'])
def login():
    """
    Login Endpoint

    Flow:
    1️⃣ Receive email, password
    2️⃣ Find user in DB
    3️⃣ Verify password hash
    4️⃣ Generate JWT tokens (24h expiry)
    5️⃣ Return user info + tokens

    Responses:
      200 ✅ Login successful
      401 ❌ Wrong password
      404 ❌ User not found
    """

    data = request.get_json() or {}

    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # Step 1: Lookup user
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Step 2: Verify password
    if not verify_password(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401

    # Upgrade legacy Werkzeug hashes to bcrypt on successful login.
    try:
        if user.password_hash and not user.password_hash.startswith("$2"):
            user.password_hash = hash_password(password)
            db.session.commit()
    except Exception:
        db.session.rollback()

    # Step 3: Create JWT tokens
    access_token = create_access_token(
        identity=user.user_id,
        additional_claims={
            "tenant_id": user.tenant_id,
            "email": user.email,
            "role": user.role
        }
    )
    refresh_token = create_refresh_token(identity=user.user_id)

    # Step 4: Prepare user info
    providers = UserEmailProvider.query.filter(
        UserEmailProvider.user_id == user.user_id,
        UserEmailProvider.is_active.is_(True),
        UserEmailProvider.email_connected.is_(True),
    ).all()
    connected_providers = sorted({p.provider for p in providers})

    user_info = {
        "user_id": user.user_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "email_connected": bool(getattr(user, "email_connected", False)),
        "connected_email_providers": connected_providers,
    }

    # Step 5: Return response
    return jsonify({
        "message": "Login successful",
        "user": user_info,
        "access_token": access_token,
        "refresh_token": refresh_token
    }), 200


@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """
    Refresh Token Endpoint
    - Requires a valid refresh token
    - Returns a new access token
    """

    current_user_id = get_jwt_identity()
    user = User.query.filter_by(user_id=current_user_id).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    new_access_token = create_access_token(
        identity=user.user_id,
        additional_claims={
            "tenant_id": user.tenant_id,
            "email": user.email,
            "role": user.role
        }
    )

    return jsonify({
        "access_token": new_access_token
    }), 200

# for saqib: (move or change as needed)

@bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    """
    Return current logged-in user's info.
    - Requires valid access token
    """

    current_user_id = get_jwt_identity()
    user = User.query.filter_by(user_id=current_user_id).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    user_info = {
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role
    }

    return jsonify({"user": user_info}), 200


@bp.route('/logout', methods=['POST', 'OPTIONS'])
@jwt_required()
def logout():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    jwt_payload = get_jwt()
    jti = jwt_payload.get("jti")
    token_type = jwt_payload.get("type", "access")
    exp = jwt_payload.get("exp")
    user_id = get_jwt_identity()

    expires_at = None
    if exp:
        try:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            expires_at = None

    if jti:
        exists = TokenBlocklist.query.filter_by(jti=jti).first()
        if not exists:
            db.session.add(TokenBlocklist(jti=jti, token_type=token_type, user_id=user_id, expires_at=expires_at))
            db.session.commit()

    return jsonify({"message": "Logged out"}), 200


@bp.route('/forgot-password', methods=['POST', 'OPTIONS'])
def forgot_password():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = User.query.filter_by(email=email).first()
    # Always return success to avoid account enumeration
    if not user:
        return jsonify({"message": "If that email exists, a reset link has been sent."}), 200

    try:
        raw_token, _record = create_reset_token(user.user_id)
        base = Config.PASSWORD_RESET_URL or f"{Config.FRONTEND_BASE_URL.rstrip('/')}/reset-password"
        reset_link = f"{base}?token={raw_token}"

        # Attempt template-based transactional send; fall back to a minimal email if template is missing.
        try:
            send_transactional_email(
                template_key="password_reset",
                tenant_id=user.tenant_id,
                to_email=user.email,
                variables={
                    "reset_link": reset_link,
                    "first_name": user.first_name or "",
                    "email": user.email,
                },
                user_id=user.user_id,
            )
        except Exception as send_err:
            # Log but do not fail the flow; avoid leaking details to client.
            current_app.logger.exception(f"Password reset email send failed: {send_err}")
        return jsonify({"message": "If that email exists, a reset link has been sent."}), 200
    except Exception as e:
        current_app.logger.exception(f"Failed to start password reset: {e}")
        # Still avoid account enumeration; report generic message.
        return jsonify({"message": "If that email exists, a reset link has been sent."}), 200


@bp.route('/reset-password', methods=['POST', 'OPTIONS'])
def reset_password():
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.get_json() or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("new_password")
    if not token or not new_password:
        return jsonify({"error": "token and new_password are required"}), 400

    reset = find_valid_token(token)
    if not reset:
        return jsonify({"error": "Invalid or expired reset token"}), 400

    user = User.query.filter_by(user_id=reset.user_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        user.password_hash = hash_password(new_password)
        db.session.commit()
        mark_token_used(reset)
        return jsonify({"message": "Password reset successful"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to reset password", "details": str(e)}), 500
