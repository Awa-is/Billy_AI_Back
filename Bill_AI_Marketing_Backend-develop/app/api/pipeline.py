from flask import Blueprint, jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt
from app.models.profile import Profile
from app.models.company import Company
from app.models.post import Post
from app.models.signal import Signal
from app.models.email import Email

bp = Blueprint('pipeline', __name__)

@bp.route('/stats', methods=['GET'])
@jwt_required()
def get_pipeline_stats():
    """
    Get statistics for the pipeline (profiles, companies, posts, signals, emails).
    
    Optional Query Params:
    - job_id: Filter by specific processing job (not fully implemented as stats are usually global or tenant-level)
    
    Returns:
    {
        "profiles": { "total": 0, "scraped": 0, "pending": 0, "failed": 0 },
        "companies": { "total": 0 },
        "posts": { "total": 0 },
        "signals": { "total": 0 },
        "emails": { "total": 0 }
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    # Job Context
    job_id = request.args.get('job_id')
    profile_ids = []
    job_start_time = None

    if job_id:
        from app.models.job import Job
        import json
        from datetime import timedelta
        
        job = Job.query.get(job_id)
        if job:
            # Adjust start time back by 30 seconds to capture profiles created in same batch
            job_start_time = job.created_at - timedelta(seconds=30)
            
            if job.result_data:
                try:
                    data = json.loads(job.result_data)
                    profile_ids = data.get('profile_ids', [])
                except:
                    pass

    # Profiles Stats
    profile_query = Profile.query.filter_by(tenant_id=tenant_id)
    if profile_ids:
        # If we have specific profile IDs from the job, use them
        profile_query = profile_query.filter(Profile.profile_id.in_(profile_ids))
    elif job_start_time:
         # Fallback if no IDs but we have time (shoudn't happen with new logic, but safe)
         profile_query = profile_query.filter(Profile.created_at >= job_start_time)

    profiles_total = profile_query.count()
    profiles_scraped = profile_query.filter_by(status='scraped').count()
    profiles_pending = profile_query.filter(Profile.status.in_(['url_only', 'processing'])).count()
    profiles_failed = profile_query.filter_by(status='scraping_failed').count()

    # Companies Stats
    companies_query = Company.query.filter_by(tenant_id=tenant_id)
    if profile_ids:
        # Filter companies linked to these profiles (via name match)
        # This assumes profiles have been scraped/populated with company names
        # We use a subquery or join-like filter
        from app.extensions import db
        target_company_names = db.session.query(Profile.company_name).\
            filter(Profile.tenant_id == tenant_id).\
            filter(Profile.profile_id.in_(profile_ids)).\
            filter(Profile.company_name != None).\
            distinct().all()
        
        names = [r[0] for r in target_company_names if r[0]]
        if names:
            companies_query = companies_query.filter(Company.name.in_(names))
        else:
             # If profiles have no company names yet, we theoretically have 0 processed companies
            companies_query = companies_query.filter(Company.tenant_id == 'non-existent')
            
    companies_total = companies_query.count()

    # Posts Stats
    posts_query = Post.query.filter_by(tenant_id=tenant_id)
    if job_start_time:
        posts_query = posts_query.filter(Post.created_at >= job_start_time)
    posts_total = posts_query.count()

    # Signals Stats
    signals_query = Signal.query.filter_by(tenant_id=tenant_id)
    if job_start_time:
        signals_query = signals_query.filter(Signal.created_at >= job_start_time)
    signals_total = signals_query.count()

    # Emails Stats
    emails_query = Email.query.filter_by(tenant_id=tenant_id)
    if job_start_time:
        emails_query = emails_query.filter(Email.created_at >= job_start_time)
    emails_total = emails_query.count()

    # Check for templates
    from app.models.email_template import EmailTemplate
    has_template = EmailTemplate.query.filter(
        (EmailTemplate.tenant_id == tenant_id) | 
        ((EmailTemplate.is_default == True))
    ).first() is not None

    stats = {
        "profiles": {
            "total": profiles_total,
            "scraped": profiles_scraped,
            "pending": profiles_pending,
            "failed": profiles_failed
        },
        "companies": {
            "total": companies_total
        },
        "posts": {
            "total": posts_total
        },
        "signals": {
            "total": signals_total
        },
        "emails": {
            "total": emails_total
        },
        "template_status": {
            "has_template": has_template,
            "message": "No email template found" if not has_template else "Ready"
        }
    }

    return jsonify(stats), 200


@bp.route('/retry-emails', methods=['POST'])
@jwt_required()
def retry_emails():
    """
    Manually trigger email generation for existing signals.
    Useful after uploading settings or templates.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from app.tasks.signal_tasks import generate_emails_from_signals_task
        task = generate_emails_from_signals_task.delay(tenant_id)
        return jsonify({
            "message": "Email generation queued", 
            "task_id": task.id
        }), 200
    except Exception as e:
        current_app.logger.error(f"Failed to retry emails: {e}")
        return jsonify({"error": str(e)}), 500
