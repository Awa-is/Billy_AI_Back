"""
Signals API Endpoints

GET /api/signals - List all signals for tenant
GET /api/signals/<signal_id> - Get specific signal
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
from app.extensions import db
from app.models.signal import Signal
from app.models.post import Post
from app.models.profile import Profile
from app.models.company import Company
from sqlalchemy import or_, and_
from datetime import datetime
import math

bp = Blueprint('signals', __name__)


def signal_to_dict(signal, include_full_details=False):
    """Convert Signal model to dictionary."""
    data = {
        "signal_id": signal.signal_id,
        "signal_type": signal.signal_type,
        "score": signal.score,
        "keywords": signal.keywords.split(',') if signal.keywords else [],
        "created_at": signal.created_at.isoformat() if signal.created_at else None
    }
    
    if include_full_details:
        data["metadata"] = signal.signal_metadata
        
        # Include post details
        if signal.post:
            data["post"] = {
                "post_id": signal.post.post_id,
                "post_text": signal.post.post_text[:500] if signal.post.post_text else None,
                "post_date": signal.post.post_date.isoformat() if signal.post.post_date else None
            }
        
        # Include profile details
        if signal.profile:
            data["profile"] = {
                "profile_id": signal.profile.profile_id,
                "person_name": signal.profile.person_name,
                "email": signal.profile.email
            }
        
        # Include company details
        if signal.company:
            data["company"] = {
                "company_id": signal.company.company_id,
                "name": signal.company.name,
                "linkedin_url": signal.company.linkedin_url
            }
    else:
        # List view - include summary info
        if signal.company:
            data["company"] = {
                "company_id": signal.company.company_id,
                "name": signal.company.name
            }
    
    return data


@bp.route('', methods=['GET'])
@jwt_required()
def list_signals():
    """
    List all signals for the authenticated tenant.
    
    Query Parameters:
        - signal_type: Filter by signal type (product_launch, company_news, career_move, linkedin_activity)
        - company_id: Filter by company
        - min_score: Minimum score threshold
        - page: Page number (default: 1)
        - per_page: Items per page (default: 20, max: 100)
        
    Returns:
        List of signals with pagination
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("List signals: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get query parameters
    signal_type = request.args.get('signal_type')
    company_id = request.args.get('company_id')
    min_score = request.args.get('min_score', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    # Build query
    query = Signal.query.filter_by(tenant_id=tenant_id)
    
    # Apply filters
    if signal_type:
        query = query.filter(Signal.signal_type == signal_type)
    
    if company_id:
        query = query.filter(Signal.company_id == company_id)
    
    if min_score is not None:
        query = query.filter(Signal.score >= min_score)
    
    # Get total count
    total = query.count()
    
    # Paginate
    pagination = query.order_by(Signal.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    signals = pagination.items
    
    # Convert to dict
    signals_data = [signal_to_dict(signal, include_full_details=False) for signal in signals]
    
    return jsonify({
        "signals": signals_data,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": math.ceil(total / per_page) if per_page > 0 else 0
        }
    }), 200


@bp.route('/<signal_id>', methods=['GET'])
@jwt_required()
def get_signal(signal_id):
    """
    Get a specific signal by ID.
    
    Returns:
        Signal details with full information
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Get signal: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    signal = Signal.query.filter_by(
        signal_id=signal_id,
        tenant_id=tenant_id
    ).first()
    
    if not signal:
        return jsonify({"error": "Signal not found"}), 404
    
    return jsonify({"signal": signal_to_dict(signal, include_full_details=True)}), 200

