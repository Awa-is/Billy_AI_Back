"""
Conversations API Endpoint

GET /api/conversations?filter=<filter> - List conversations with filtering

Single endpoint approach with filter query parameter:
- filter=active (default): Shows all except drafts, sorted by replied first, then lastActivity DESC
- filter=inbox: Shows only "replied" status, sorted by lastActivity DESC
- filter=sent: Shows "awaiting" + "sent" status, sorted by lastActivity DESC
- filter=drafts: Shows only "draft" status, sorted by updatedAt DESC

Response includes counts for ALL tabs so frontend can show badge numbers.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from app.extensions import db
from app.models.email import Email
from app.models.profile import Profile
from app.models.post import Post
from app.models.signal import Signal
from sqlalchemy import or_, and_, func, case
from sqlalchemy.orm import joinedload
from datetime import datetime
import math
import json

bp = Blueprint('conversations', __name__)


def get_last_activity(email):
    """
    Get the last activity timestamp for an email.
    Priority: sent_at > updated_at > created_at
    """
    if email.sent_at:
        return email.sent_at
    if email.updated_at:
        return email.updated_at
    return email.created_at


def email_to_dict(email):
    """Convert Email model to dictionary for response matching API spec."""
    profile = email.profile
    last_activity = get_last_activity(email)
    
    # Generate preview from email body (first 100 characters)
    preview = None
    if email.body:
        preview = email.body[:100] + "..." if len(email.body) > 100 else email.body
    
    # Determine unread status: replied status AND not yet read
    unread = email.status == 'replied' and email.read_at is None
    
    # Message count (for now: 1, can be enhanced later to count replies)
    message_count = 1
    
    # Determine status for UI
    status = email.status
    if getattr(email, 'has_reply', False):
        status = 'replied'
    elif status == 'sent':
        status = 'awaiting'
        
    return {
        "id": email.email_id,  # Using email_id as id
        "contactName": profile.person_name if profile else None,
        "contactEmail": profile.email if profile else (email.recipients if email.recipients else None),
        "subject": email.subject,
        "lastActivity": last_activity.isoformat() if last_activity else None,
        "status": status,  # replied | awaiting | draft | sent
        "preview": preview,
        "messageCount": (getattr(email, 'reply_count', 0) or 0) + 1,
        "unread": unread
    }


@bp.route('', methods=['GET'])
@jwt_required()
def list_conversations():
    """
    List conversations with filtering.
    
    Used In UI: ConversationList.tsx - Left sidebar showing all conversations
    When Called: On page load + when user clicks tabs (Active, Inbox, Sent, Drafts) + when user searches
    
    Query Parameters:
        - filter: Filter type (active, inbox, sent, drafts). Default: active
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - search: Search in subject, contact name, email
    
    Response includes counts for all tabs (active, inbox, sent, drafts).
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get query parameters
    filter_type = request.args.get('filter', 'active').lower()
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    search = request.args.get('search', '').strip()
    
    # Validate pagination
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20
    
    # Validate filter
    valid_filters = ['active', 'inbox', 'sent', 'drafts']
    if filter_type not in valid_filters:
        return jsonify({
            "error": "Invalid filter",
            "message": f"Filter must be one of: {', '.join(valid_filters)}"
        }), 400
    
    # Base query - only non-deleted emails for tenant
    base_query = Email.query.filter(
        Email.tenant_id == tenant_id,
        Email.deleted_at.is_(None)
    )
    
    # Calculate counts for ALL tabs (for badge numbers)
    counts = {
        "active": base_query.filter(Email.status != 'draft').count(),
        "inbox": base_query.filter(Email.has_reply == True).count(),
        "sent": base_query.filter(Email.status == 'sent').count(),
        "drafts": base_query.filter(Email.status == 'draft').count(),
    }
    
    # Apply filter logic
    query = base_query
    
    if filter_type == 'active':
        # Active: all except drafts
        # Sort: replied first, then by lastActivity DESC
        query = query.filter(Email.status != 'draft')
        
        # For sorting: replied (has_reply=True) first, then by lastActivity
        # lastActivity = sent_at > updated_at > created_at
        last_activity_expr = func.coalesce(
            Email.sent_at,
            Email.updated_at,
            Email.created_at
        )
        
        # Order by: has_reply Desc (True=1, False=0), then lastActivity DESC
        query = query.order_by(
            Email.has_reply.desc().nullslast(),
            last_activity_expr.desc()
        )
        
    elif filter_type == 'inbox':
        # Inbox: only has_reply=True
        query = query.filter(Email.has_reply == True)
        
        last_activity_expr = func.coalesce(
            Email.sent_at,
            Email.updated_at,
            Email.created_at
        )
        query = query.order_by(last_activity_expr.desc())
        
    elif filter_type == 'sent':
        # Sent: status='sent' (includes awaiting)
        query = query.filter(Email.status == 'sent')
        
        last_activity_expr = func.coalesce(
            Email.sent_at,
            Email.updated_at,
            Email.created_at
        )
        query = query.order_by(last_activity_expr.desc())
        
    elif filter_type == 'drafts':
        # Drafts: only "draft" status
        # Sort by updatedAt DESC (fallback to created_at if updated_at is None)
        query = query.filter(Email.status == 'draft')
        updated_at_expr = func.coalesce(Email.updated_at, Email.created_at)
        query = query.order_by(updated_at_expr.desc())
    
    # Apply search filter if provided
    if search:
        # Join Profile for searching contact name and email
        query = query.join(Profile, Email.profile_id == Profile.profile_id, isouter=True)
        
        # Search in subject, contact name, and email
        search_filter = or_(
            Email.subject.ilike(f'%{search}%'),
            Profile.person_name.ilike(f'%{search}%'),
            Profile.email.ilike(f'%{search}%'),
            Email.recipients.ilike(f'%{search}%')
        )
        query = query.filter(search_filter)
    
    # Eager load relationships to avoid N+1 queries
    query = query.options(
        joinedload(Email.post).joinedload(Post.company),
        joinedload(Email.profile),
        joinedload(Email.signal)
    )
    
    # Get total count for current filter (after search)
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    emails = query.offset(offset).limit(limit).all()
    
    # Convert to dictionaries matching API spec
    conversations = [email_to_dict(email) for email in emails]
    
    # Calculate pagination metadata
    total_pages = math.ceil(total / limit) if total > 0 else 0
    
    return jsonify({
        "data": conversations,  # Changed from "conversations" to "data" to match spec
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "totalPages": total_pages  # Changed from "total_pages" to "totalPages" to match spec
        },
        "counts": counts  # Counts for ALL tabs (for badge numbers)
    }), 200


@bp.route('/<conversation_id>', methods=['GET'])
@jwt_required()
def get_conversation(conversation_id):
    """
    Get full conversation thread with all messages.
    
    Used In UI: EmailDetailView.tsx - Right panel showing full email content
    When Called: When user clicks on a conversation card in the left sidebar
    
    Returns the complete email thread including all sent/received messages,
    attachments, and full contact details.
    
    URL Parameters:
        - id: Conversation ID (email_id)
    
    Response (200 OK):
    {
        "id": "email-uuid",
        "contactName": "Sarah Johnson",
        "contactEmail": "sarah.johnson@techcorp.com",
        "subject": "Partnership Proposal - Q4 Initiative",
        "status": "replied",
        "unread": false,
        "messages": [
            {
                "id": "email-uuid",
                "direction": "outbound",
                "body": "Dear Sarah,\n\nI wanted to reach out regarding...",
                "sentAt": "2025-10-05T14:00:00Z",
                "attachments": []
            }
        ],
        "contact": {
            "id": "profile-uuid",
            "firstName": "Sarah",
            "lastName": "Johnson",
            "email": "sarah.johnson@techcorp.com",
            "companyName": "TechCorp",
            "seniority": "VP of Operations"
        }
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get email (conversation) by ID
    email = Email.query.options(
        joinedload(Email.post).joinedload(Post.company),
        joinedload(Email.profile),
        joinedload(Email.signal)
    ).filter_by(
        email_id=conversation_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Conversation not found"}), 404
    
    profile = email.profile
    
    # Build messages array
    # For now, we return the email as a single outbound message
    # If status is 'replied', we can add logic to detect replies later
    messages = []
    
    # Main email as outbound message
    outbound_message = {
        "id": email.email_id,
        "direction": "outbound",
        "body": email.body,
        "sentAt": email.sent_at.isoformat() if email.sent_at else email.created_at.isoformat() if email.created_at else None,
        "attachments": []  # TODO: Add attachment support
    }
    messages.append(outbound_message)
    
    # If status is 'replied', we could add an inbound message placeholder
    # For now, we'll just return the outbound message
    # In the future, this could query for actual reply emails
    
    # Build contact details
    contact = None
    if profile:
        # Extract seniority from job_title or experiences
        seniority = profile.job_title or None
        if not seniority and profile.experiences:
            try:
                experiences = json.loads(profile.experiences) if isinstance(profile.experiences, str) else profile.experiences
                if experiences and len(experiences) > 0:
                    # Get most recent experience
                    latest_exp = experiences[0] if isinstance(experiences, list) else experiences
                    seniority = latest_exp.get('title') if isinstance(latest_exp, dict) else None
            except:
                pass
        
        contact = {
            "id": profile.profile_id,
            "firstName": profile.first_name or (profile.person_name.split()[0] if profile.person_name and ' ' in profile.person_name else None),
            "lastName": profile.last_name or (profile.person_name.split()[-1] if profile.person_name and ' ' in profile.person_name else None),
            "email": profile.email or email.recipients,
            "companyName": profile.company_name or profile.company or None,
            "seniority": seniority
        }
    else:
        # Fallback for manual emails without profile
        contact = {
            "id": None,
            "firstName": None,
            "lastName": None,
            "email": email.recipients,
            "companyName": None,
            "seniority": None
        }
    
    # Determine unread status: replied status AND not yet read
    unread = email.status == 'replied' and email.read_at is None
    
    return jsonify({
        "id": email.email_id,
        "contactName": profile.person_name if profile else email.recipients,
        "contactEmail": profile.email if profile else email.recipients,
        "subject": email.subject,
        "status": email.status,  # replied | awaiting | draft | sent
        "unread": unread,
        "messages": messages,
        "contact": contact
    }), 200


@bp.route('/<conversation_id>/read', methods=['PATCH'])
@jwt_required()
def mark_conversation_as_read(conversation_id):
    """
    Marks a conversation as read.
    
    Used In UI: ConversationList.tsx + EmailDetailView.tsx
    When Called: Automatically when user opens a conversation with unread messages
    UI Elements: Blue unread indicator dot disappears from conversation card
    
    Response (200 OK):
    {
        "id": "conversation-uuid",
        "unread": false
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get the conversation (email) by ID
    email = Email.query.filter_by(
        email_id=conversation_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Conversation not found"}), 404
    
    # Mark as read by setting read_at timestamp
    if email.read_at is None:
        email.read_at = datetime.utcnow()
        db.session.commit()
    
    return jsonify({
        "id": email.email_id,
        "unread": False
    }), 200
