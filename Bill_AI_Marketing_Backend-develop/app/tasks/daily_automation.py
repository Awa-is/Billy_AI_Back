"""
Daily Automation Tasks
Runs automatically to scrape posts, analyze them, detect signals, and generate emails.
"""

from app.tasks.celery_app import celery_app
from app import create_app
from app.extensions import db
from app.models.job import Job
from app.models.company import Company
from app.models.post import Post
from app.models.tenant import Tenant
from app.services.signal_detection import detect_signals_from_analyzed_posts
from app.services.signal_email_generation import generate_emails_for_signal
from datetime import datetime, timedelta
import logging
import uuid

logger = logging.getLogger(__name__)


def _get_flask_app():
    """Get Flask app instance for context."""
    from app import create_app
    return create_app()


@celery_app.task(bind=True, name='daily_automation_task')
def daily_automation_task(self, tenant_id: str = None):
    """
    Daily automation task that:
    1. Scrapes posts for active companies
    2. Analyzes new posts
    3. Detects signals from analyzed posts
    4. Generates email drafts from signals
    
    Args:
        tenant_id: Optional tenant ID. If None, processes all tenants.
        
    Returns:
        dict with automation results
    """
    app = _get_flask_app()
    
    with app.app_context():
        try:
            logger.info(f"Starting daily automation task for tenant_id={tenant_id or 'all'}")
            
            # Get tenants to process
            if tenant_id:
                tenants = [Tenant.query.filter_by(tenant_id=tenant_id).first()]
                tenants = [t for t in tenants if t]  # Filter out None
            else:
                tenants = Tenant.query.all()
            
            if not tenants:
                logger.warning("No tenants found for daily automation")
                return {
                    "status": "success",
                    "message": "No tenants found",
                    "tenants_processed": 0
                }
            
            total_results = {
                "status": "success",
                "tenants_processed": 0,
                "companies_scraped": 0,
                "posts_analyzed": 0,
                "signals_detected": 0,
                "emails_generated": 0,
                "tenant_results": []
            }
            
            # Process each tenant
            for tenant in tenants:
                tenant_result = {
                    "tenant_id": tenant.tenant_id,
                    "companies_scraped": 0,
                    "posts_analyzed": 0,
                    "signals_detected": 0,
                    "emails_generated": 0
                }
                
                try:
                    logger.info(f"Processing tenant: {tenant.tenant_id}")
                    
                    # Step 1: Get active companies for this tenant
                    active_companies = Company.query.filter_by(
                        tenant_id=tenant.tenant_id,
                        is_active=True
                    ).all()
                    
                    logger.info(f"Found {len(active_companies)} active companies for tenant {tenant.tenant_id}")
                    
                    if not active_companies:
                        logger.info(f"No active companies for tenant {tenant.tenant_id}")
                        total_results["tenant_results"].append(tenant_result)
                        continue
                    
                    # Step 2: Scrape posts for each active company
                    from app.tasks.scraper import scrape_company_posts
                    
                    for company in active_companies:
                        try:
                            # Create job for scraping
                            scrape_job_id = str(uuid.uuid4())
                            scrape_job = Job(
                                job_id=scrape_job_id,
                                tenant_id=tenant.tenant_id,
                                job_type='company_scrape',
                                status='pending',
                                total_items=100
                            )
                            db.session.add(scrape_job)
                            db.session.commit()
                            
                            # Scrape posts (call Celery task synchronously)
                            logger.info(f"Scraping posts for company: {company.name} ({company.company_id})")
                            from app.tasks.scraper import scrape_company_posts
                            # Use .apply() for synchronous execution (self is provided by Celery)
                            scrape_result = scrape_company_posts.apply(
                                args=(scrape_job_id, tenant.tenant_id, company.company_id, 100)
                            ).get()
                            
                            if scrape_result.get('status') == 'success':
                                tenant_result["companies_scraped"] += 1
                                total_results["companies_scraped"] += 1
                                logger.info(f"Successfully scraped {scrape_result.get('posts_scraped', 0)} posts for {company.name}")
                            else:
                                logger.warning(f"Failed to scrape posts for {company.name}: {scrape_result.get('message')}")
                                
                        except Exception as scrape_error:
                            logger.error(f"Error scraping company {company.name}: {scrape_error}", exc_info=True)
                            continue
                    
                    # Step 3: Analyze new posts (posts without analyzed_at)
                    from app.tasks.ai_analyzer import analyze_post
                    
                    unanalyzed_posts = Post.query.filter(
                        Post.tenant_id == tenant.tenant_id,
                        Post.analyzed_at.is_(None)
                    ).limit(50).all()  # Limit to avoid overwhelming the system
                    
                    logger.info(f"Found {len(unanalyzed_posts)} unanalyzed posts for tenant {tenant.tenant_id}")
                    
                    for post in unanalyzed_posts:
                        try:
                            # Create job for analysis
                            analyze_job_id = str(uuid.uuid4())
                            analyze_job = Job(
                                job_id=analyze_job_id,
                                tenant_id=tenant.tenant_id,
                                job_type='post_analysis',
                                status='pending',
                                total_items=1
                            )
                            db.session.add(analyze_job)
                            db.session.commit()
                            
                            # Analyze post (call Celery task synchronously)
                            logger.debug(f"Analyzing post: {post.post_id}")
                            from app.tasks.ai_analyzer import analyze_post
                            # Use .apply() for synchronous execution (self is provided by Celery)
                            analyze_result = analyze_post.apply(
                                args=(analyze_job_id, tenant.tenant_id, post.post_id)
                            ).get()
                            
                            if analyze_result.get('status') == 'success':
                                tenant_result["posts_analyzed"] += 1
                                total_results["posts_analyzed"] += 1
                                
                        except Exception as analyze_error:
                            logger.error(f"Error analyzing post {post.post_id}: {analyze_error}", exc_info=True)
                            continue
                    
                    # Step 4: Detect signals from analyzed posts
                    logger.info(f"Detecting signals for tenant {tenant.tenant_id}")
                    signals = detect_signals_from_analyzed_posts(tenant.tenant_id)
                    tenant_result["signals_detected"] = len(signals)
                    total_results["signals_detected"] += len(signals)
                    logger.info(f"Detected {len(signals)} signals for tenant {tenant.tenant_id}")
                    
                    # Step 5: Generate email drafts from signals
                    from app.models.profile import Profile
                    
                    emails_generated = 0
                    for signal in signals:
                        try:
                            # Get profiles for this signal's company
                            # Signal has company_id, get company name
                            company_name = None
                            if signal.company_id:
                                company = Company.query.filter_by(company_id=signal.company_id).first()
                                if company:
                                    company_name = company.name
                            
                            profiles = []
                            if company_name:
                                profiles = Profile.query.filter_by(
                                    tenant_id=tenant.tenant_id,
                                    company_name=company_name
                                ).all()
                            
                            # If no profiles match company name, get all profiles for tenant
                            if not profiles:
                                profiles = Profile.query.filter_by(
                                    tenant_id=tenant.tenant_id
                                ).limit(10).all()  # Limit to avoid too many emails
                            
                            # Generate emails for each profile
                            for profile in profiles:
                                try:
                                    from app.services.signal_email_generation import generate_email_from_signal
                                    
                                    email = generate_email_from_signal(
                                        signal=signal,
                                        profile=profile,
                                        tenant_id=tenant.tenant_id,
                                        sender_name="Team"
                                    )
                                    
                                    if email:
                                        emails_generated += 1
                                        
                                except Exception as email_error:
                                    logger.error(f"Error generating email for signal {signal.signal_id} and profile {profile.profile_id}: {email_error}", exc_info=True)
                                    continue
                                    
                        except Exception as signal_error:
                            logger.error(f"Error processing signal {signal.signal_id}: {signal_error}", exc_info=True)
                            continue
                    
                    tenant_result["emails_generated"] = emails_generated
                    total_results["emails_generated"] += emails_generated
                    logger.info(f"Generated {emails_generated} email drafts for tenant {tenant.tenant_id}")
                    
                    total_results["tenants_processed"] += 1
                    total_results["tenant_results"].append(tenant_result)
                    
                except Exception as tenant_error:
                    logger.error(f"Error processing tenant {tenant.tenant_id}: {tenant_error}", exc_info=True)
                    total_results["tenant_results"].append({
                        "tenant_id": tenant.tenant_id,
                        "error": str(tenant_error)
                    })
                    continue
            
            logger.info(f"Daily automation completed: {total_results}")
            return total_results
            
        except Exception as e:
            logger.exception(f"Daily automation task failed: {e}")
            return {
                "status": "error",
                "message": str(e)
            }


@celery_app.task(bind=True, name='daily_automation_for_tenant')
def daily_automation_for_tenant(self, tenant_id: str):
    """
    Wrapper task for daily automation for a specific tenant.
    Calls the main daily_automation_task with tenant_id.
    """
    return daily_automation_task(tenant_id=tenant_id)
