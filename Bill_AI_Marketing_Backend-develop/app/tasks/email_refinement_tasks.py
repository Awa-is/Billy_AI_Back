"""
Celery tasks for refining emails with AI.
"""

import logging
from datetime import datetime
from typing import Dict, Any

from app.tasks.celery_app import celery_app
from app.extensions import db
from app.models.email import Email
from app.models.job import Job
from app.services.email_refinement import refine_email_content
from app.models.user import User

logger = logging.getLogger(__name__)


def _get_flask_app():
    """Get Flask app instance for context."""
    from app import create_app
    return create_app()


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def refine_email_task(self, job_id: str, email_id: str, tenant_id: str, user_id: str = None, refinement_options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Refine an email draft using AI with optional refinement criteria.
    
    Args:
        job_id: Job ID tracking this task
        email_id: Email ID to refine
        tenant_id: Tenant ID for validation
        user_id: Optional user ID for sender name
        refinement_options: Optional dict with refinement options:
            - tone: str (Formal, Informal, Friendly, Professional, Conversational, Persuasive, Educational)
            - make_shorter: bool
            - make_longer: bool
            - fix_spelling_grammar: bool
        
    Returns:
        Dict with success status and refined content or error details
    """
    app = _get_flask_app()
    
    with app.app_context():
        job = None
        try:
            # Get job record
            job = Job.query.filter_by(job_id=job_id).first()
            if not job:
                logger.error(f"Job not found: {job_id}")
                return {"success": False, "error": "Job not found"}
            
            # Update job status to processing
            job.status = 'processing'
            job.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Starting email refinement: job_id={job_id}, email_id={email_id}, tenant_id={tenant_id}")
            
            # Get email
            email = Email.query.filter_by(
                email_id=email_id,
                tenant_id=tenant_id
            ).filter(Email.deleted_at.is_(None)).first()
            
            if not email:
                error_msg = "Email not found"
                logger.error(f"Email not found: email_id={email_id}, tenant_id={tenant_id}")
                job.status = 'failed'
                job.error_message = error_msg
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return {"success": False, "error": error_msg}
            
            # Validate email can be refined (must be draft)
            if email.status != 'draft':
                error_msg = f"Cannot refine email with status '{email.status}'. Only draft emails can be refined."
                logger.warning(f"Attempted to refine non-draft email: email_id={email_id}, status={email.status}")
                job.status = 'failed'
                job.error_message = error_msg
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return {"success": False, "error": error_msg}
            
            # Get sender name
            sender_name = "Team"
            if user_id:
                user = User.query.filter_by(user_id=user_id).first()
                if user:
                    sender_name = user.first_name or "Team"
            
            # Refine email content (pass user_id for user-specific instructions and refinement options)
            refined_content = refine_email_content(
                email=email,
                tenant_id=tenant_id,
                sender_name=sender_name,
                user_id=user_id,
                refinement_options=refinement_options or {}
            )
            
            # Update email with refined content
            # Preserve all metadata (signal_id, post_id, profile_id, etc.)
            email.subject = refined_content['subject']
            email.body = refined_content['body']
            # Note: All other fields (signal_id, post_id, profile_id, approval_status, etc.) remain unchanged
            
            db.session.commit()
            
            # Update job status
            job.status = 'completed'
            job.success_count = 1
            job.completed_items = 1
            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            
            result_data = {
                "email_id": email_id,
                "subject": email.subject,
                "body_preview": email.body[:100] + "..." if len(email.body) > 100 else email.body
            }
            job.result_data = str(result_data).replace("'", '"')  # Simple JSON string conversion
            db.session.commit()
            
            logger.info(f"Email refined successfully: email_id={email_id}, job_id={job_id}")
            
            return {
                "success": True,
                "email_id": email_id,
                "subject": email.subject,
                "body": email.body
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Email refinement failed: email_id={email_id}, job_id={job_id}, error={error_msg}")
            
            if job:
                job.status = 'failed'
                job.error_message = error_msg
                job.completed_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                db.session.commit()
            
            return {
                "success": False,
                "error": error_msg
            }
