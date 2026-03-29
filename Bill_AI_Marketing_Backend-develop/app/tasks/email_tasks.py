import logging
from datetime import datetime

from app.tasks.celery_app import celery_app
from app.extensions import db
from app.models.campaign import Campaign, CampaignProfile
from app.models.email_template import EmailTemplate
from app.models.post import Post
from app.models.profile import Profile
from app.models.user import User
from app.services.email_generation import generate_email_record

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def generate_campaign_emails_task(self, campaign_id, template_id, tenant_id, user_id):
    campaign = Campaign.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id).first()
    if not campaign:
        logger.error("Campaign not found for task", extra={"campaign_id": campaign_id, "tenant_id": tenant_id})
        return {"generated": 0, "failed": 0}

    template = EmailTemplate.query.filter(
        (EmailTemplate.template_id == template_id) &
        ((EmailTemplate.tenant_id == tenant_id) | (EmailTemplate.is_default.is_(True)))
    ).first()
    if not template:
        logger.error("Template not found for task", extra={"template_id": template_id, "tenant_id": tenant_id})
        return {"generated": 0, "failed": 0}

    user = User.query.filter_by(user_id=user_id).first()
    sender_name = user.first_name or "Team" if user else "Team"

    pending_links = CampaignProfile.query.filter_by(campaign_id=campaign_id, status='pending').all()
    generated = 0
    failed = 0

    for link in pending_links:
        profile = Profile.query.filter_by(profile_id=link.profile_id, tenant_id=tenant_id).first()
        post = Post.query.filter_by(post_id=campaign.post_id, tenant_id=tenant_id).first()

        if not profile or not post:
            link.status = 'email_failed'
            failed += 1
            continue

        try:
            email = generate_email_record(
                tenant_id=tenant_id,
                post=post,
                profile=profile,
                template=template,
                sender_name=sender_name,
                campaign_id=campaign_id
            )
            link.status = 'email_generated'
            link.email_id = email.email_id
            generated += 1
        except Exception as exc:
            logger.exception("Failed to generate email for campaign profile", extra={
                "campaign_id": campaign_id,
                "profile_id": link.profile_id,
                "error": str(exc)
            })
            link.status = 'email_failed'
            failed += 1

        db.session.commit()

    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    return {"generated": generated, "failed": failed}

