from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, validates, ValidationError
from app.extensions import db
from app.models.email import Email
from app.models.email_template import EmailTemplate
from app.models.post import Post
from app.models.profile import Profile
from app.models.user import User
from app.models.campaign import Campaign, CampaignProfile
from app.services.email_generation import generate_email_record
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
from datetime import datetime
import uuid
import math

bp = Blueprint('emails', __name__)


class GenerateEmailSchema(Schema):
    post_id = fields.Str(required=True, error_messages={"required": "post_id is required"})
    profile_id = fields.Str(required=True, error_messages={"required": "profile_id is required"})
    template_id = fields.Str(required=True, error_messages={"required": "template_id is required"})


generate_email_schema = GenerateEmailSchema()


def email_to_dict(email, include_full_details=False):
    """Convert Email model to dictionary with related data."""
    data = {
        "email_id": email.email_id,
        "subject": email.subject,
        "status": email.status,
        "has_reply": getattr(email, 'has_reply', False),
        "reply_count": getattr(email, 'reply_count', 0),
        "created_at": email.created_at.isoformat() if email.created_at else None
    }
    
    if include_full_details:
        data["body"] = email.body
        data["post_id"] = email.post_id
        data["profile_id"] = email.profile_id
        data["template_id"] = email.template_id
        
        # Include post details
        if email.post:
            data["post"] = {
                "post_id": email.post.post_id,
                "company_name": email.post.company.name if email.post.company else None,
                "post_text": email.post.post_text
            }
        
        # Include profile details
        if email.profile:
            data["profile"] = {
                "profile_id": email.profile.profile_id,
                "person_name": email.profile.person_name,
                "headline": email.profile.headline
            }
        
        # Find campaign through CampaignProfile
        campaign_profile = CampaignProfile.query.filter_by(email_id=email.email_id).first()
        if campaign_profile and campaign_profile.campaign:
            data["campaign"] = {
                "campaign_id": campaign_profile.campaign.campaign_id,
                "name": campaign_profile.campaign.name
            }
    else:
        # List view - include summary info
        if email.post and email.post.company:
            data["post"] = {
                "post_id": email.post.post_id,
                "company_name": email.post.company.name
            }
        
        if email.profile:
            data["profile"] = {
                "profile_id": email.profile.profile_id,
                "person_name": email.profile.person_name
            }
        
        # Find campaign
        campaign_profile = CampaignProfile.query.filter_by(email_id=email.email_id).first()
        if campaign_profile and campaign_profile.campaign:
            data["campaign"] = {
                "campaign_id": campaign_profile.campaign.campaign_id,
                "name": campaign_profile.campaign.name
            }
    
    return data


@bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_email():
    """
    Generate a single personalized email using Claude API.
    
    Request Body:
        {
            "post_id": "post-uuid",
            "profile_id": "profile-uuid",
            "template_id": "template-uuid"
        }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    user = User.query.filter_by(user_id=current_user_id).first()
    sender_name = user.first_name or "Team" if user else "Team"
    
    data = request.get_json() or {}
    
    try:
        validated = generate_email_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    post_id = validated['post_id']
    profile_id = validated['profile_id']
    template_id = validated['template_id']
    
    # Validate post exists and belongs to tenant
    post = Post.query.filter_by(post_id=post_id).first()
    if not post:
        return jsonify({"error": "Post not found"}), 404
    
    if post.tenant_id != tenant_id:
        return jsonify({"error": "Post does not belong to your tenant"}), 403
    
    # Validate profile exists and belongs to tenant
    profile = Profile.query.filter_by(profile_id=profile_id).first()
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    if profile.tenant_id != tenant_id:
        return jsonify({"error": "Profile does not belong to your tenant"}), 403
    
    # Validate template exists and belongs to tenant (or is default)
    template = EmailTemplate.query.filter(
        EmailTemplate.template_id == template_id,
        (EmailTemplate.tenant_id == tenant_id) | (EmailTemplate.is_default == True)
    ).first()
    
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Check if profile is in a campaign
    campaign_profile = CampaignProfile.query.filter_by(profile_id=profile_id).first()
    campaign_id = campaign_profile.campaign_id if campaign_profile else None
    
    try:
        # Generate email using Claude
        email = generate_email_record(
            tenant_id=tenant_id,
            post=post,
            profile=profile,
            template=template,
            sender_name=sender_name,
            campaign_id=campaign_id
        )
        
        return jsonify({"email": email_to_dict(email)}), 201
        
    except Exception as e:
        return jsonify({"error": "Failed to generate email", "details": str(e)}), 500


class UpdateEmailSchema(Schema):
    subject = fields.Str(validate=lambda x: len(x) <= 500, error_messages={"validator_failed": "Subject must be max 500 characters"})
    body = fields.Str(validate=lambda x: len(x) <= 10000, error_messages={"validator_failed": "Body must be max 10000 characters"})
    status = fields.Str()
    to = fields.Str(allow_none=True)
    cc = fields.Str(allow_none=True)
    bcc = fields.Str(allow_none=True)
    attachmentIds = fields.List(fields.Str(), allow_none=True)
    

update_email_schema = UpdateEmailSchema()


@bp.route('/<email_id>', methods=['PATCH', 'PUT'])
@jwt_required()
def update_email(email_id):
    """
    Update email (subject, body, status, recipients).
    Cannot update if status='sent'.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Filter out soft-deleted emails in query
    email = Email.query.filter_by(
        email_id=email_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Email not found"}), 404
    
    # Cannot update sent emails
    if email.status == 'sent':
        return jsonify({"error": "Cannot update sent email"}), 400
    
    data = request.get_json() or {}
    
    print(f"DEBUG: update_email called for {email_id}", flush=True)
    print(f"DEBUG: update_email payload: {data}", flush=True)
    
    try:
        validated = update_email_schema.load(data, partial=True)
        print(f"DEBUG: Validated data: {validated}", flush=True)
    except ValidationError as err:
        print(f"DEBUG: Validation error: {err.messages}", flush=True)
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    # Update fields
    if 'subject' in validated:
        if len(validated['subject']) > 500:
            return jsonify({"error": "Subject must be max 500 characters"}), 400
        email.subject = validated['subject']
    
    if 'body' in validated:
        if len(validated['body']) > 10000:
            return jsonify({"error": "Body must be max 10000 characters"}), 400
        email.body = validated['body']

    if 'recipients' in validated: # Map recipients if passed directly
        email.recipients = validated['recipients']
    
    if 'to' in validated:
        email.recipients = validated['to']

    if 'cc' in validated:
        email.cc = validated['cc']
        
    if 'bcc' in validated:
        email.bcc = validated['bcc']
    
    print(f"DEBUG: Updated email.recipients to: {email.recipients}", flush=True)
    
    if 'status' in validated:
        new_status = validated['status']
        # Cannot change from sent to draft
        if email.status == 'sent' and new_status == 'draft':
            return jsonify({"error": "Cannot change sent email to draft"}), 400
        email.status = new_status
    
    db.session.commit()
    print(f"DEBUG: DB Commit successful for {email_id}", flush=True)
    return jsonify(email_to_dict(email)), 200



class CreateDraftSchema(Schema):
    to = fields.Str(required=True, error_messages={"required": "To address is required"})
    subject = fields.Str(required=True, error_messages={"required": "Subject is required"})
    body = fields.Str(required=True, error_messages={"required": "Body is required"})
    cc = fields.Str(allow_none=True)
    bcc = fields.Str(allow_none=True)
    contact_id = fields.Str(allow_none=True)
    attachmentIds = fields.List(fields.Str(), allow_none=True)


create_draft_schema = CreateDraftSchema()


@bp.route('/drafts', methods=['POST'])
@jwt_required()
def create_draft():
    """
    Create a new manual draft email.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    data = request.get_json() or {}
    
    try:
        validated = create_draft_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    # Check for profile if contact_id provided
    profile_id = None
    if validated.get('contact_id'):
        # Try to find profile by ID (assuming contact_id maps to profile_id)
        # Note: Frontend sends numeric contactId sometimes, but Profile uses UUID strings.
        # If it's a manual draft, maybe we search by email?
        # For now, let's try to find profile by email if contact_id fails or is missing
        profile = Profile.query.filter_by(
            profile_id=str(validated['contact_id']), 
            tenant_id=tenant_id
        ).first()
        if profile:
            profile_id = profile.profile_id
    
    if not profile_id:
        # Try to find by email
        recipient_email = validated['to']
        profile = Profile.query.filter_by(
            email=recipient_email,
            tenant_id=tenant_id
        ).first()
        if profile:
            profile_id = profile.profile_id

    # Create Email
    email = Email(
        email_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        profile_id=profile_id,
        recipients=validated['to'],
        subject=validated['subject'],
        body=validated['body'],
        status='draft',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    db.session.add(email)
    db.session.commit()
    
    # Handle attachments if needed (logic to link attachments to email)
    # Assuming Attachment model has email_id foreign key
    # if validated.get('attachmentIds'):
    #     attachments = Attachment.query.filter(Attachment.id.in_(validated['attachmentIds'])).all()
    #     for att in attachments:
    #         att.email_id = email.email_id
    #     db.session.commit()
    
    return jsonify({
        "email_id": email.email_id,
        "id": email.email_id, # return both for frontend compatibility
        "email": email_to_dict(email)
    }), 201


@bp.route('', methods=['GET'])
@jwt_required()
def list_emails():
    """
    List all emails for the tenant with filtering, pagination, and search.
    
    Query Parameters:
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
        - status: Filter by status (draft, sent, failed)
        - approval_status: Filter by approval_status (pending, approved, rejected)
        - post_id: Filter by post
        - profile_id: Filter by profile
        - campaign_id: Filter by campaign
        - search: Search in subject and recipient name
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get query parameters
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    status = request.args.get('status')
    approval_status = request.args.get('approval_status')
    post_id = request.args.get('post_id')
    profile_id = request.args.get('profile_id')
    campaign_id = request.args.get('campaign_id')
    search = request.args.get('search', '').strip()
    
    # Validate pagination
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20
    
    # Base query - only non-deleted emails for tenant
    query = Email.query.filter(
        Email.tenant_id == tenant_id,
        Email.deleted_at.is_(None)
    )
    
    # Track if we need to join Profile for search
    needs_profile_join = bool(search)
    needs_campaign_join = bool(campaign_id)
    
    # Join Profile if needed for search
    if needs_profile_join:
        query = query.join(Profile, Email.profile_id == Profile.profile_id, isouter=True)
    
    # Join CampaignProfile if needed for campaign filter
    if needs_campaign_join:
        query = query.join(
            CampaignProfile,
            and_(
                CampaignProfile.email_id == Email.email_id,
                CampaignProfile.campaign_id == campaign_id
            ),
            isouter=False
        )
    
    # Apply filters
    if status:
        query = query.filter(Email.status == status)
    
    if approval_status:
        query = query.filter(Email.approval_status == approval_status)
    
    if post_id:
        query = query.filter(Email.post_id == post_id)
    
    if profile_id:
        query = query.filter(Email.profile_id == profile_id)
        
    # Check for has_reply filter
    has_reply_param = request.args.get('has_reply')
    if has_reply_param is not None:
        is_true = has_reply_param.lower() == 'true'
        query = query.filter(Email.has_reply == is_true)
    
    if search:
        # Search in subject and profile name
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Email.subject.ilike(search_pattern),
                Profile.person_name.ilike(search_pattern)
            )
        )
    
    # Sort by created_at DESC (newest first)
    query = query.order_by(Email.created_at.desc())
    
    # Eager load relationships to avoid N+1 queries
    query = query.options(
        joinedload(Email.post).joinedload(Post.company),
        joinedload(Email.profile)
    )
    
    # Get total count before pagination (need to count before eager loading)
    total_query = Email.query.filter(
        Email.tenant_id == tenant_id,
        Email.deleted_at.is_(None)
    )
    if status:
        total_query = total_query.filter(Email.status == status)
    if post_id:
        total_query = total_query.filter(Email.post_id == post_id)
    if profile_id:
        total_query = total_query.filter(Email.profile_id == profile_id)
    if campaign_id:
        total_query = total_query.join(
            CampaignProfile,
            and_(
                CampaignProfile.email_id == Email.email_id,
                CampaignProfile.campaign_id == campaign_id
            ),
            isouter=False
        )
    if search:
        total_query = total_query.join(Profile, Email.profile_id == Profile.profile_id, isouter=True).filter(
            or_(
                Email.subject.ilike(f"%{search}%"),
                Profile.person_name.ilike(f"%{search}%")
            )
        )
    total = total_query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    emails = query.offset(offset).limit(limit).all()
    
    # Calculate total pages
    total_pages = math.ceil(total / limit) if total > 0 else 0
    
    return jsonify({
        "emails": [email_to_dict(email, include_full_details=False) for email in emails],
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": total_pages
        }
    }), 200


@bp.route('/<email_id>', methods=['GET'])
@jwt_required()
def get_email(email_id):
    """
    Get single email details with related data.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Eager load relationships and filter out soft-deleted emails
    email = Email.query.options(
        joinedload(Email.post).joinedload(Post.company),
        joinedload(Email.profile)
    ).filter_by(
        email_id=email_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Email not found"}), 404
    
    return jsonify({"email": email_to_dict(email, include_full_details=True)}), 200



    
    return jsonify({"email": email_to_dict(email, include_full_details=True)}), 200


@bp.route('/<email_id>', methods=['DELETE'])
@jwt_required()
def delete_email(email_id):
    """
    Hard delete email from database.
    Cannot delete if status='sent'.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Filter out soft-deleted emails in query
    email = Email.query.filter_by(
        email_id=email_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Email not found"}), 404
    
    # Cannot delete sent emails
    if email.status == 'sent':
        return jsonify({"error": "Cannot delete sent email"}), 400
    
    # Hard delete - remove from database
    db.session.delete(email)
    db.session.commit()

    return jsonify({"message": "Email deleted successfully"}), 200


@bp.route('/<email_id>/send', methods=['POST'])
@jwt_required()
def send_email(email_id):
    """
    Send a single email via AWS SES (async).
    
    Returns:
        202 Accepted with job_id
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Validate email exists and belongs to tenant (filter out soft-deleted)
    email = Email.query.filter_by(
        email_id=email_id,
        tenant_id=tenant_id
    ).filter(Email.deleted_at.is_(None)).first()
    
    if not email:
        return jsonify({"error": "Email not found"}), 404
    
    # Validate email status
    if email.status == 'sent':
        return jsonify({"error": "Email already sent"}), 400
    
    # Validate recipient has email address
    recipient_email = email.recipients
    if not recipient_email and email.profile_id:
         profile = Profile.query.filter_by(profile_id=email.profile_id, tenant_id=tenant_id).first()
         if profile:
             recipient_email = profile.email

    if not recipient_email or not recipient_email.strip():
        # Only enforce profile/email check if no override recipient
        if not email.profile_id:
            return jsonify({"error": "Email has no recipients and no associated profile"}), 400
        
        profile = Profile.query.filter_by(profile_id=email.profile_id, tenant_id=tenant_id).first()
        if not profile:
            return jsonify({"error": "Profile not found"}), 404
        
        if not profile.email or not profile.email.strip():
             return jsonify({"error": "Recipient email not found"}), 400
    
    # Validate email sending configuration (OAuth or SES)
    # OAuth will be tried first if user has connected account, SES as fallback
    # No need to validate here as both will be checked in the task
    
    # Get current user ID for OAuth sending
    current_user_id = get_jwt_identity()
    
    # Start async task
    from app.tasks.email_sender_tasks import send_single_email_task
    task = send_single_email_task.delay(email_id=email_id, tenant_id=tenant_id, user_id=current_user_id)
    
    return jsonify({
        "message": "Email sending started",
        "job_id": task.id,
        "email_id": email_id
    }), 202

