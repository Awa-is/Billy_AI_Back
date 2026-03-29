from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, validates, ValidationError
from datetime import datetime

from app.extensions import db
from app.models.campaign import Campaign, CampaignProfile
from app.models.post import Post
from app.models.profile import Profile

bp = Blueprint('campaigns', __name__)

VALID_CAMPAIGN_STATUSES = {'draft', 'active', 'completed'}
VALID_PROFILE_STATUSES = {'pending', 'email_generated', 'email_sent', 'email_failed'}


class CreateCampaignSchema(Schema):
    post_id = fields.Str(required=True)
    profile_ids = fields.List(fields.Str(), required=True)
    name = fields.Str(required=True)
    status = fields.Str(missing='draft')

    @validates('name')
    def validate_name(self, value):
        if not value or not value.strip():
            raise ValidationError("Name is required")
        if len(value) > 255:
            raise ValidationError("Name must be less than 255 characters")

    @validates('profile_ids')
    def validate_profile_ids(self, value):
        if not value:
            raise ValidationError("At least one profile_id is required")
        if len(value) > 1000:
            raise ValidationError("Too many profiles (max 1000)")

    @validates('status')
    def validate_status(self, value):
        if value not in VALID_CAMPAIGN_STATUSES:
            raise ValidationError(f"Status must be one of: {', '.join(VALID_CAMPAIGN_STATUSES)}")


class AddProfilesSchema(Schema):
    profile_ids = fields.List(fields.Str(), required=True)

    @validates('profile_ids')
    def validate_profile_ids(self, value):
        if not value:
            raise ValidationError("At least one profile_id is required")
        if len(value) > 1000:
            raise ValidationError("Too many profiles (max 1000)")


create_campaign_schema = CreateCampaignSchema()
add_profiles_schema = AddProfilesSchema()


def campaign_to_dict(campaign, include_profiles=False):
    data = {
        "campaign_id": campaign.campaign_id,
        "name": campaign.name,
        "post_id": campaign.post_id,
        "status": campaign.status,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None
    }

    if include_profiles:
        items = CampaignProfile.query.filter_by(campaign_id=campaign.campaign_id).all()
        profiles = []
        for link in items:
            profiles.append({
                "profile_id": link.profile_id,
                "person_name": link.profile.person_name if link.profile else None,
                "linkedin_url": link.profile.linkedin_url if link.profile else None,
                "status": link.status,
                "email_id": link.email_id,
                "added_at": link.added_at.isoformat() if link.added_at else None
            })
        data["profiles"] = profiles
        data["profile_count"] = len(profiles)
    else:
        data["profile_count"] = CampaignProfile.query.filter_by(campaign_id=campaign.campaign_id).count()

    return data


@bp.route('', methods=['POST'])
@jwt_required()
def create_campaign():
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json() or {}
    try:
        data = create_campaign_schema.load(payload)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400

    post = Post.query.filter_by(post_id=data['post_id']).first()
    if not post:
        return jsonify({"error": "Post not found"}), 404
    if post.tenant_id != tenant_id:
        return jsonify({"error": "Post does not belong to your tenant"}), 403

    profiles = Profile.query.filter(Profile.profile_id.in_(data['profile_ids'])).all()
    found_ids = {p.profile_id for p in profiles}
    missing = set(data['profile_ids']) - found_ids
    if missing:
        return jsonify({"error": f"Profiles not found: {list(missing)}"}), 404
    invalid = [p for p in profiles if p.tenant_id != tenant_id]
    if invalid:
        return jsonify({"error": "Some profiles do not belong to your tenant"}), 403

    unique_profile_ids = list(found_ids)

    campaign = Campaign(
        tenant_id=tenant_id,
        post_id=post.post_id,
        name=data['name'].strip(),
        status=data.get('status', 'draft')
    )
    db.session.add(campaign)
    db.session.flush()

    for profile_id in unique_profile_ids:
        db.session.add(CampaignProfile(
            campaign_id=campaign.campaign_id,
            profile_id=profile_id,
            status='pending'
        ))

    db.session.commit()
    return jsonify({"campaign": campaign_to_dict(campaign, include_profiles=True)}), 201


@bp.route('', methods=['GET'])
@jwt_required()
def list_campaigns():
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    page = max(1, int(request.args.get('page', 1)))
    limit = min(100, max(1, int(request.args.get('limit', 20))))

    query = Campaign.query.filter_by(tenant_id=tenant_id)
    status_filter = request.args.get('status')
    if status_filter and status_filter in VALID_CAMPAIGN_STATUSES:
        query = query.filter(Campaign.status == status_filter)

    total = query.count()
    items = (query.order_by(Campaign.created_at.desc())
             .offset((page - 1) * limit)
             .limit(limit)
             .all())

    return jsonify({
        "campaigns": [campaign_to_dict(c) for c in items],
        "page": page,
        "limit": limit,
        "total": total
    }), 200


@bp.route('/<campaign_id>', methods=['GET'])
@jwt_required()
def get_campaign(campaign_id):
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"campaign": campaign_to_dict(campaign, include_profiles=True)}), 200


@bp.route('/<campaign_id>/add-profiles', methods=['POST'])
@jwt_required()
def add_profiles(campaign_id):
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json() or {}
    try:
        data = add_profiles_schema.load(payload)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400

    profiles = Profile.query.filter(Profile.profile_id.in_(data['profile_ids'])).all()
    found_ids = {p.profile_id for p in profiles}
    missing = set(data['profile_ids']) - found_ids
    if missing:
        return jsonify({"error": f"Profiles not found: {list(missing)}"}), 404
    invalid = [p for p in profiles if p.tenant_id != tenant_id]
    if invalid:
        return jsonify({"error": "Some profiles do not belong to your tenant"}), 403

    existing_links = CampaignProfile.query.filter(
        CampaignProfile.campaign_id == campaign_id,
        CampaignProfile.profile_id.in_(found_ids)
    ).all()
    existing_ids = {link.profile_id for link in existing_links}

    new_ids = [pid for pid in found_ids if pid not in existing_ids]
    if not new_ids:
        return jsonify({"error": "All profiles already linked to this campaign"}), 400

    for profile_id in new_ids:
        db.session.add(CampaignProfile(
            campaign_id=campaign_id,
            profile_id=profile_id,
            status='pending'
        ))

    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": f"Added {len(new_ids)} profile(s) to campaign",
        "campaign": campaign_to_dict(campaign, include_profiles=True)
    }), 200


@bp.route('/<campaign_id>/profiles/<profile_id>', methods=['DELETE'])
@jwt_required()
def remove_profile(campaign_id, profile_id):
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403

    link = CampaignProfile.query.filter_by(campaign_id=campaign_id, profile_id=profile_id).first()
    if not link:
        return jsonify({"error": "Profile not found in this campaign"}), 404

    db.session.delete(link)
    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"message": "Profile removed from campaign"}), 200


@bp.route('/<campaign_id>', methods=['DELETE'])
@jwt_required()
def delete_campaign(campaign_id):
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403

    db.session.delete(campaign)
    db.session.commit()
    
    return jsonify({"message": "Campaign deleted successfully"}), 200


@bp.route('/<campaign_id>/generate-emails', methods=['POST'])
@jwt_required()
def generate_campaign_emails(campaign_id):
    """
    Generate emails for all profiles in a campaign (async task).
    
    Request Body:
        {
            "template_id": "template-uuid"
        }
    
    Returns:
        202 Accepted with job_id
    """
    from marshmallow import Schema, fields, ValidationError
    from app.models.email_template import EmailTemplate
    from app.tasks.email_tasks import generate_campaign_emails_task
    
    class GenerateCampaignEmailsSchema(Schema):
        template_id = fields.Str(required=True, error_messages={"required": "template_id is required"})
    
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Validate campaign exists and belongs to tenant
    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    
    try:
        validated = GenerateCampaignEmailsSchema().load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    template_id = validated['template_id']
    
    # Validate template exists and belongs to tenant (or is default)
    template = EmailTemplate.query.filter(
        EmailTemplate.template_id == template_id,
        (EmailTemplate.tenant_id == tenant_id) | (EmailTemplate.is_default == True)
    ).first()
    
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Start async task
    task = generate_campaign_emails_task.delay(
        campaign_id=campaign_id,
        template_id=template_id,
        tenant_id=tenant_id,
        user_id=current_user_id
    )
    
    return jsonify({
        "message": "Email generation started",
        "job_id": task.id,
        "campaign_id": campaign_id
    }), 202


@bp.route('/<campaign_id>/send-emails', methods=['POST'])
@jwt_required()
def send_campaign_emails(campaign_id):
    """
    Send all draft emails in a campaign via AWS SES (async).
    
    Returns:
        202 Accepted with job_id
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Validate campaign exists and belongs to tenant
    campaign = Campaign.query.filter_by(campaign_id=campaign_id).first()
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    
    if campaign.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    # Validate AWS SES configuration
    try:
        from app.services.email_sender import get_ses_client
        get_ses_client()
    except ValueError as e:
        return jsonify({"error": "AWS SES configuration error", "details": str(e)}), 500
    
    # Start async task
    from app.tasks.email_sender_tasks import send_campaign_emails_task
    task = send_campaign_emails_task.delay(campaign_id=campaign_id, tenant_id=tenant_id)
    
    return jsonify({
        "message": "Campaign email sending started",
        "job_id": task.id,
        "campaign_id": campaign_id
    }), 202


