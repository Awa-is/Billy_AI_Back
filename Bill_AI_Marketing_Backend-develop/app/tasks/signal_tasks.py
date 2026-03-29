"""
Background Tasks for Signal Detection and Email Generation
"""

from app.tasks.celery_app import celery_app
from app import create_app
from app.extensions import db
from app.models.job import Job
from app.models.signal import Signal
from app.models.profile import Profile
from app.services.signal_detection import detect_signals_from_analyzed_posts
from app.services.signal_email_generation import generate_emails_for_signal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def detect_signals_task(self, tenant_id: str):
    """
    Background task to detect signals from analyzed posts.
    
    Args:
        tenant_id: Tenant ID to detect signals for
        
    Returns:
        dict with detection results
    """
    app = create_app()
    
    with app.app_context():
        try:
            logger.info(f"Starting signal detection for tenant {tenant_id}")
            
            # Detect signals from analyzed posts
            signals = detect_signals_from_analyzed_posts(tenant_id)
            
            logger.info(f"Detected {len(signals)} signals for tenant {tenant_id}")
            
            return {
                "status": "success",
                "tenant_id": tenant_id,
                "signals_detected": len(signals),
                "signal_ids": [s.signal_id for s in signals]
            }
            
        except Exception as e:
            logger.exception(f"Signal detection failed for tenant {tenant_id}: {e}")
            raise


@celery_app.task(bind=True, max_retries=3)
def generate_emails_from_signals_task(self, tenant_id: str, signal_id: str = None):
    """
    Background task to generate email drafts from detected signals.
    
    Args:
        tenant_id: Tenant ID
        signal_id: Optional specific signal ID (if None, processes all recent signals)
        
    Returns:
        dict with generation results
    """
    app = create_app()
    
    with app.app_context():
        try:
            logger.info(f"Starting email generation from signals for tenant {tenant_id}")
            
            # Get signals to process
            if signal_id:
                signals = Signal.query.filter_by(
                    tenant_id=tenant_id,
                    signal_id=signal_id
                ).all()
            else:
                # Get all recent signals without emails yet
                signals = Signal.query.filter_by(tenant_id=tenant_id).all()
            
            if not signals:
                logger.info(f"No signals found for tenant {tenant_id}")
                return {
                    "status": "success",
                    "tenant_id": tenant_id,
                    "emails_generated": 0
                }
            
            total_emails = 0
            for signal in signals:
                # Check if emails already generated for this signal
                from app.models.email import Email
                existing_count = Email.query.filter_by(
                    tenant_id=tenant_id,
                    signal_id=signal.signal_id
                ).count()
                
                if existing_count > 0:
                    logger.debug(f"Emails already generated for signal {signal.signal_id}")
                    continue
                
                # Generate emails for this signal
                count = generate_emails_for_signal(
                    signal=signal,
                    tenant_id=tenant_id,
                    sender_name="Team"
                )
                total_emails += count
            
            logger.info(f"Generated {total_emails} email drafts from signals for tenant {tenant_id}")
            
            return {
                "status": "success",
                "tenant_id": tenant_id,
                "emails_generated": total_emails,
                "signals_processed": len(signals)
            }
            
        except Exception as e:
            logger.exception(f"Email generation from signals failed for tenant {tenant_id}: {e}")
            raise


@celery_app.task(bind=True, max_retries=3)
def process_signals_and_emails_task(self, tenant_id: str):
    """
    Combined task: Detect signals and generate emails.
    
    This is the main task that should be called after posts are analyzed.
    
    Args:
        tenant_id: Tenant ID
        
    Returns:
        dict with results
    """
    app = create_app()
    
    with app.app_context():
        try:
            logger.info(f"Processing signals and emails for tenant {tenant_id}")
            
            # Step 1: Detect signals
            signals = detect_signals_from_analyzed_posts(tenant_id)
            logger.info(f"Detected {len(signals)} signals")
            
            # Step 2: Generate emails for each signal
            total_emails = 0
            for signal in signals:
                count = generate_emails_for_signal(
                    signal=signal,
                    tenant_id=tenant_id,
                    sender_name="Team"
                )
                total_emails += count
            
            logger.info(f"Generated {total_emails} email drafts from {len(signals)} signals")
            
            return {
                "status": "success",
                "tenant_id": tenant_id,
                "signals_detected": len(signals),
                "emails_generated": total_emails
            }
            
        except Exception as e:
            logger.exception(f"Process signals and emails failed for tenant {tenant_id}: {e}")
            raise


