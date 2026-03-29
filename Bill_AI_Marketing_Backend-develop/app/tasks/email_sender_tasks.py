"""
Celery tasks for sending emails via AWS SES.
"""
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.tasks.celery_app import celery_app
from app.extensions import db
from app.models.email import Email
from app.models.profile import Profile
from app.models.campaign import Campaign, CampaignProfile
from app.services.email_sender import send_email, send_email_via_ses, is_transient_error
from app.models.user import User

logger = logging.getLogger(__name__)


def _get_flask_app():
    """Get Flask app instance for context."""
    from app import create_app
    return create_app()


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_single_email_task(self, email_id: str, tenant_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Send a single email via AWS SES.
    
    Args:
        email_id: Email record ID
        tenant_id: Tenant ID for validation
        user_id: Optional user ID for OAuth sending
    
    Returns:
        Dict with success status and message_id or error details
    """
    app = _get_flask_app()
    with app.app_context():
        email = Email.query.filter_by(email_id=email_id, tenant_id=tenant_id).first()
        
        if not email:
            logger.error("Email not found for sending", extra={"email_id": email_id, "tenant_id": tenant_id})
            return {"success": False, "error": "Email not found"}
        
        logger.info(f"DEBUG: Processing email task {email_id}. Recipients in DB: {email.recipients}, Profile ID: {email.profile_id}")
        print(f"DEBUG: Processing email task {email_id}. Recipients in DB: {email.recipients}, Profile ID: {email.profile_id}", flush=True)

        # Validate email status
        if email.status != 'draft':
            error_msg = f"Cannot send email with status '{email.status}'. Only 'draft' emails can be sent."
            logger.warning("Attempted to send non-draft email", extra={"email_id": email_id, "status": email.status})
            email.status = 'failed'
            email.error_message = error_msg
            db.session.commit()
            return {"success": False, "error": error_msg}
        
        # Determine recipient email
        recipient_email = email.recipients
        if not recipient_email and email.profile_id:
            profile = Profile.query.filter_by(profile_id=email.profile_id, tenant_id=tenant_id).first()
            if profile:
                recipient_email = profile.email
        
        if not recipient_email or not recipient_email.strip():
            # If still no email, check profile strictness
            if not email.profile_id:
                 error_msg = "Email has no recipients and no associated profile"
                 logger.error("Email missing recipients and profile", extra={"email_id": email_id})
                 email.status = 'failed'
                 email.error_message = error_msg
                 db.session.commit()
                 return {"success": False, "error": error_msg}
            else:
                 # Profile was present but no email found
                 error_msg = "Recipient email not found in profile or email record"
                 logger.warning("No recipient email found", extra={"email_id": email_id})
                 email.status = 'failed'
                 email.error_message = error_msg
                 db.session.commit()
                 return {"success": False, "error": error_msg}

        # Get user_id if not provided (try to get from tenant's first user)
        if not user_id:
            user = User.query.filter_by(tenant_id=tenant_id, is_active=True).first()
            if user:
                user_id = user.user_id
                logger.debug(f"Using user_id={user_id} from tenant for email_id={email_id}")
        
        logger.info(f"DEBUG: Final recipient: {recipient_email}")
        print(f"DEBUG: Final recipient: {recipient_email}", flush=True)

        # Send email via OAuth (with SES fallback)
        try:
            result = send_email(
                recipient_email=recipient_email,
                subject=email.subject,
                body=email.body,
                user_id=user_id,
                cc=None, # DB schema update needed for CC: email.cc if hasattr(email, 'cc') else None,
                bcc=None # DB schema update needed for BCC: email.bcc if hasattr(email, 'bcc') else None
            )
            
            # Check if the email was actually sent (not just silently skipped)
            if not result.get('success'):
                method = result.get('method', 'unknown')
                if method == 'ses_disabled':
                    error_msg = (
                        "Email not sent: No OAuth email provider is connected for this account "
                        "and AWS SES is not configured. Please connect a Gmail or Outlook account "
                        "from the Settings > Email Connection page."
                    )
                else:
                    error_msg = f"Email send returned unsuccessful result: method={method}"
                
                logger.warning("Email send unsuccessful - no provider available", extra={
                    "email_id": email_id,
                    "method": method,
                    "user_id": user_id
                })
                email.status = 'failed'
                email.error_message = error_msg
                email.sent_at = datetime.utcnow()
                db.session.commit()
                
                campaign_profile = CampaignProfile.query.filter_by(email_id=email_id).first()
                if campaign_profile:
                    campaign_profile.status = 'email_failed'
                    db.session.commit()
                
                return {"success": False, "error": error_msg}
            
            # Update email record
            email.status = 'sent'
            email.message_id = result['message_id']
            email.sent_at = datetime.utcnow()
            email.error_message = None
            db.session.commit()
            
            logger.info("Email sent successfully", extra={
                "email_id": email_id,
                "message_id": result['message_id'],
                "recipient": recipient_email,
                "method": result.get('method', 'ses'),
                "provider": result.get('provider')
            })
            
            # Update campaign profile if linked
            campaign_profile = CampaignProfile.query.filter_by(email_id=email_id).first()
            if campaign_profile:
                campaign_profile.status = 'email_sent'
                db.session.commit()
            
            return {
                "success": True,
                "message_id": result['message_id'],
                "sent_at": email.sent_at.isoformat()
            }
            
        except ValueError as e:
            # Validation errors - don't retry
            error_msg = str(e)
            logger.error("Email sending validation error", extra={"email_id": email_id, "error": error_msg})
            email.status = 'failed'
            email.error_message = error_msg
            email.sent_at = datetime.utcnow()
            db.session.commit()
            
            # Update campaign profile
            campaign_profile = CampaignProfile.query.filter_by(email_id=email_id).first()
            if campaign_profile:
                campaign_profile.status = 'email_failed'
                db.session.commit()
            
            return {"success": False, "error": error_msg}
        
        except Exception as e:
            # Check if this is a transient error that should be retried
            if is_transient_error(e) and self.request.retries < self.max_retries:
                logger.warning("Transient error sending email, will retry", extra={
                    "email_id": email_id,
                    "retry": self.request.retries + 1,
                    "error": str(e)
                })
                raise  # Let Celery retry
            
            # Permanent error - mark as failed
            error_msg = str(e)
            logger.error("Failed to send email", extra={"email_id": email_id, "error": error_msg})
            email.status = 'failed'
            email.error_message = error_msg
            email.sent_at = datetime.utcnow()
            db.session.commit()
            
            # Update campaign profile
            campaign_profile = CampaignProfile.query.filter_by(email_id=email_id).first()
            if campaign_profile:
                campaign_profile.status = 'email_failed'
                db.session.commit()
            
            return {"success": False, "error": error_msg}


@celery_app.task(bind=True)
def send_campaign_emails_task(self, campaign_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Send all draft emails in a campaign via AWS SES.
    
    Args:
        campaign_id: Campaign ID
        tenant_id: Tenant ID for validation
    
    Returns:
        Dict with total, sent, failed counts and failed email details
    """
    app = _get_flask_app()
    with app.app_context():
        campaign = Campaign.query.filter_by(campaign_id=campaign_id, tenant_id=tenant_id).first()
        
        if not campaign:
            logger.error("Campaign not found for sending", extra={"campaign_id": campaign_id, "tenant_id": tenant_id})
            return {"total": 0, "sent": 0, "failed": 0, "failed_emails": []}
        
        # Find all emails in campaign with status='draft'
        campaign_profiles = CampaignProfile.query.filter_by(
            campaign_id=campaign_id
        ).filter(
            CampaignProfile.email_id.isnot(None)
        ).all()
        
        email_ids = [cp.email_id for cp in campaign_profiles if cp.email_id]
        
        if not email_ids:
            logger.info("No emails found in campaign", extra={"campaign_id": campaign_id})
            return {"total": 0, "sent": 0, "failed": 0, "failed_emails": []}
        
        # Get draft emails
        emails = Email.query.filter(
            Email.email_id.in_(email_ids),
            Email.tenant_id == tenant_id,
            Email.status == 'draft'
        ).all()
        
        total = len(emails)
        sent = 0
        failed = 0
        failed_emails: List[Dict[str, Any]] = []
        
        logger.info("Starting campaign email sending", extra={
            "campaign_id": campaign_id,
            "total_emails": total
        })
        
        for email in emails:
            try:
                # Get recipient email
                if not email.profile_id:
                    failed += 1
                    failed_emails.append({
                        "email_id": email.email_id,
                        "recipient": None,
                        "error": "Email has no associated profile"
                    })
                    email.status = 'failed'
                    email.error_message = "Email has no associated profile"
                    db.session.commit()
                    continue
                
                profile = Profile.query.filter_by(profile_id=email.profile_id).first()
                if not profile or not profile.email or not profile.email.strip():
                    failed += 1
                    failed_emails.append({
                        "email_id": email.email_id,
                        "recipient": profile.email if profile else None,
                        "error": "Recipient email not found"
                    })
                    email.status = 'failed'
                    email.error_message = "Recipient email not found"
                    db.session.commit()
                    
                    # Update campaign profile
                    campaign_profile = CampaignProfile.query.filter_by(
                        campaign_id=campaign_id,
                        email_id=email.email_id
                    ).first()
                    if campaign_profile:
                        campaign_profile.status = 'email_failed'
                        db.session.commit()
                    continue
                
                # Get user_id if available (try to get from tenant's first user)
                user = User.query.filter_by(tenant_id=tenant_id, is_active=True).first()
                user_id = user.user_id if user else None
                
                # Send email via OAuth (with SES fallback)
                result = send_email(
                    recipient_email=profile.email,
                    subject=email.subject,
                    body=email.body,
                    user_id=user_id
                )
                
                # Check if the email was actually sent (not just silently skipped)
                if not result.get('success'):
                    method = result.get('method', 'unknown')
                    if method == 'ses_disabled':
                        error_msg = (
                            "Email not sent: No OAuth email provider is connected for this account "
                            "and AWS SES is not configured. Please connect a Gmail or Outlook account."
                        )
                    else:
                        error_msg = f"Email send returned unsuccessful result: method={method}"
                    
                    failed += 1
                    failed_emails.append({
                        "email_id": email.email_id,
                        "recipient": profile.email,
                        "error": error_msg
                    })
                    email.status = 'failed'
                    email.error_message = error_msg
                    email.sent_at = datetime.utcnow()
                    db.session.commit()
                    
                    campaign_profile = CampaignProfile.query.filter_by(
                        campaign_id=campaign_id,
                        email_id=email.email_id
                    ).first()
                    if campaign_profile:
                        campaign_profile.status = 'email_failed'
                        db.session.commit()
                    continue
                
                # Update email record
                email.status = 'sent'
                email.message_id = result['message_id']
                email.sent_at = datetime.utcnow()
                email.error_message = None
                db.session.commit()
                
                # Update campaign profile
                campaign_profile = CampaignProfile.query.filter_by(
                    campaign_id=campaign_id,
                    email_id=email.email_id
                ).first()
                if campaign_profile:
                    campaign_profile.status = 'email_sent'
                    db.session.commit()
                
                sent += 1
                logger.info("Campaign email sent", extra={
                    "campaign_id": campaign_id,
                    "email_id": email.email_id,
                    "message_id": result['message_id']
                })
                
            except ValueError as e:
                # Validation errors
                failed += 1
                error_msg = str(e)
                failed_emails.append({
                    "email_id": email.email_id,
                    "recipient": profile.email if profile else None,
                    "error": error_msg
                })
                email.status = 'failed'
                email.error_message = error_msg
                email.sent_at = datetime.utcnow()
                db.session.commit()
                
                # Update campaign profile
                campaign_profile = CampaignProfile.query.filter_by(
                    campaign_id=campaign_id,
                    email_id=email.email_id
                ).first()
                if campaign_profile:
                    campaign_profile.status = 'email_failed'
                    db.session.commit()
                
                logger.warning("Campaign email failed (validation)", extra={
                    "campaign_id": campaign_id,
                    "email_id": email.email_id,
                    "error": error_msg
                })
                
            except Exception as e:
                # Other errors
                failed += 1
                error_msg = str(e)
                failed_emails.append({
                    "email_id": email.email_id,
                    "recipient": profile.email if profile else None,
                    "error": error_msg
                })
                email.status = 'failed'
                email.error_message = error_msg
                email.sent_at = datetime.utcnow()
                db.session.commit()
                
                # Update campaign profile
                campaign_profile = CampaignProfile.query.filter_by(
                    campaign_id=campaign_id,
                    email_id=email.email_id
                ).first()
                if campaign_profile:
                    campaign_profile.status = 'email_failed'
                    db.session.commit()
                
                logger.error("Campaign email failed", extra={
                    "campaign_id": campaign_id,
                    "email_id": email.email_id,
                    "error": error_msg
                })
        
        logger.info("Campaign email sending completed", extra={
            "campaign_id": campaign_id,
            "total": total,
            "sent": sent,
            "failed": failed
        })
        
        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "failed_emails": failed_emails
        }

