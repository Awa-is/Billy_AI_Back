"""
API endpoints for LinkedIn posts analysis
"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt
from marshmallow import Schema, fields, validates, ValidationError
from app.extensions import db
from app.models.post import Post
from app.models.company import Company
from app.models.campaign import Campaign
from app.models.email import Email
from datetime import datetime
from sqlalchemy import and_, or_

bp = Blueprint('posts', __name__)


class BatchAnalyzeSchema(Schema):
    post_ids = fields.List(fields.Str(), required=True, error_messages={
        "required": "post_ids is required"
    })
    
    @validates('post_ids')
    def validate_post_ids(self, value):
        if not value or len(value) == 0:
            raise ValidationError("post_ids cannot be empty")
        if len(value) > 100:
            raise ValidationError("Cannot analyze more than 100 posts at once")


batch_analyze_schema = BatchAnalyzeSchema()


@bp.route('', methods=['GET'])
@jwt_required()
def list_posts():
    """
    List scraped LinkedIn posts with filtering, pagination, and sorting.
    
    Query Parameters:
        - company_id (str, optional): Filter by company ID
        - start_date (str, optional): Filter posts from this date (YYYY-MM-DD)
        - end_date (str, optional): Filter posts until this date (YYYY-MM-DD)
        - ai_judgement (str, optional): Filter by AI judgement (e.g., 'product_launch', 'other')
        - page (int, optional): Page number (default: 1)
        - limit (int, optional): Items per page (default: 20, max: 100)
    
    Returns:
        200 OK with posts array containing:
        - post_id: Post unique identifier
        - company_id: Company ID
        - company_name: Company name (from JOIN)
        - post_text: Post content
        - post_date: Post date (YYYY-MM-DD)
        - score: AI score (0-100)
        - ai_judgement: AI judgement category
        - source_url: Original LinkedIn post URL
        - created_at: When post was scraped
        - analyzed_at: When post was analyzed (if analyzed)
    
    Example:
        GET /api/posts?company_id=xxx&page=1&limit=20&ai_judgement=product_launch
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get query parameters
    company_id = request.args.get('company_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    ai_judgement = request.args.get('ai_judgement')
    
    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
    except ValueError:
        return jsonify({"error": "page and limit must be integers"}), 400
    
    # Validate pagination
    if page < 1:
        page = 1
    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100
    
    # Build query with JOIN to companies table
    query = db.session.query(Post, Company.name.label('company_name')).join(
        Company, Post.company_id == Company.company_id
    ).filter(
        Post.tenant_id == tenant_id,
        Company.tenant_id == tenant_id  # Ensure company belongs to tenant
    )
    
    # Apply filters
    if company_id:
        query = query.filter(Post.company_id == company_id)
    
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(Post.post_date >= start_dt)
        except ValueError:
            return jsonify({"error": "start_date must be in YYYY-MM-DD format"}), 400
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(Post.post_date <= end_dt)
        except ValueError:
            return jsonify({"error": "end_date must be in YYYY-MM-DD format"}), 400
    
    if ai_judgement:
        query = query.filter(Post.ai_judgement == ai_judgement)
    
    # Sort by date (newest first)
    query = query.order_by(Post.post_date.desc().nullslast(), Post.created_at.desc())
    
    # Get total count before pagination
    total_count = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    results = query.offset(offset).limit(limit).all()
    
    # Format response
    posts = []
    for post, company_name in results:
        posts.append({
            "post_id": post.post_id,
            "company_id": post.company_id,
            "company_name": company_name,
            "post_text": post.post_text,
            "post_date": post.post_date.isoformat() if post.post_date else None,
            "score": post.score,
            "ai_judgement": post.ai_judgement,
            "source_url": post.source_url,
            "created_at": post.created_at.isoformat() if post.created_at else None,
            "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
        })
    
    # Calculate pagination metadata
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
    
    return jsonify({
        "posts": posts,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
    }), 200


@bp.route('/<post_id>', methods=['GET'])
@jwt_required()
def get_post(post_id):
    """
    Retrieve a single post by its post ID.
    
    Requirements:
    - JWT authentication required
    - Post must exist and belong to the requesting tenant
    
    Returns:
    - 200: Post object with company information (same format as list_posts)
    - 401: Unauthorized (JWT missing or invalid)
    - 403: Forbidden (post belongs to different tenant)
    - 404: Post not found
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        current_app.logger.warning("Get post: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Get post: Request for post_id={post_id}, tenant_id={tenant_id}")
    
    # Query post with JOIN to Company table (similar to list_posts)
    result = db.session.query(Post, Company.name.label('company_name')).join(
        Company, Post.company_id == Company.company_id
    ).filter(
        Post.post_id == post_id,
        Post.tenant_id == tenant_id,
        Company.tenant_id == tenant_id  # Ensure company belongs to tenant
    ).first()
    
    if not result:
        # Check if post exists but belongs to different tenant
        post_exists = Post.query.filter_by(post_id=post_id).first()
        if post_exists:
            if post_exists.tenant_id != tenant_id:
                current_app.logger.warning(
                    f"Get post: Forbidden - post belongs to different tenant. "
                    f"post_id={post_id}, post_tenant_id={post_exists.tenant_id}, requesting_tenant_id={tenant_id}"
                )
                return jsonify({"error": "Forbidden"}), 403
        
        current_app.logger.warning(f"Get post: Post not found post_id={post_id}, tenant_id={tenant_id}")
        return jsonify({"error": "Post not found"}), 404
    
    post, company_name = result
    
    current_app.logger.debug(
        f"Get post: Successfully retrieved post_id={post_id}, "
        f"company_id={post.company_id}, company_name={company_name}, tenant_id={tenant_id}"
    )
    
    # Return post in same format as list_posts response
    return jsonify({
        "post_id": post.post_id,
        "company_id": post.company_id,
        "company_name": company_name,
        "post_text": post.post_text,
        "post_date": post.post_date.isoformat() if post.post_date else None,
        "score": post.score,
        "ai_judgement": post.ai_judgement,
        "source_url": post.source_url,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
    }), 200


@bp.route('/<post_id>/analyze', methods=['POST'])
@jwt_required()
def analyze_single_post(post_id):
    """
    Analyze a single post using Claude AI.
    
    Returns:
        - job_id: Job ID for tracking
        - post_id: The post ID being analyzed
        - status_url: URL to check job status
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Verify post exists and belongs to tenant
    post = Post.query.filter_by(post_id=post_id, tenant_id=tenant_id).first()
    if not post:
        return jsonify({"error": "Post not found"}), 404
    
    # Import here to avoid circular imports
    from app.tasks.ai_analyzer import analyze_post
    from app.models.job import Job
    from datetime import datetime
    import uuid
    
    try:
        # Create job record
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            tenant_id=tenant_id,
            job_type='post_analyze',
            status='pending',
            total_items=1
        )
        db.session.add(job)
        db.session.commit()
        
        current_app.logger.debug(f"Post analyze: Created job_id={job_id} for post_id={post_id}")
        
        # Start async Celery task
        try:
            task = analyze_post.delay(job_id, tenant_id, post_id)
            current_app.logger.info(f"Post analyze: Started job_id={job_id}, task_id={task.id}, post_id={post_id}")
        except Exception as celery_error:
            # Handle Celery connection errors specifically
            error_msg = str(celery_error)
            if 'Redis' in error_msg or 'broker' in error_msg.lower() or 'connection' in error_msg.lower():
                current_app.logger.error(f"Post analyze: Celery/Redis connection error: {error_msg}")
                job.status = 'failed'
                job.error_message = f"Celery/Redis connection failed: {error_msg}"
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return jsonify({
                    "error": "Celery/Redis connection failed",
                    "details": error_msg,
                    "message": "Please ensure Redis is running and accessible. Check that the Celery worker is also running."
                }), 503
            else:
                # Re-raise other errors
                raise
        
        return jsonify({
            "message": "Analysis job started",
            "job_id": job_id,
            "post_id": post_id,
            "status": "queued",
            "status_url": f"/api/jobs/{job_id}"
        }), 202
    except Exception as e:
        current_app.logger.exception(f"Post analyze: Error starting job for post_id={post_id}: {str(e)}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to start analysis job",
            "details": str(e)
        }), 500


@bp.route('/analyze-batch', methods=['POST'])
@jwt_required()
def analyze_batch_posts():
    """
    Analyze multiple posts in batch.
    
    Request body:
        {
            "post_ids": ["uuid1", "uuid2", ...]
        }
    
    Returns:
        - job_ids: List of Celery task IDs
        - posts: List of post info with job_id mapping
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    
    try:
        validated = batch_analyze_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    post_ids = validated['post_ids']
    
    # Verify all posts exist and belong to tenant
    posts = Post.query.filter(
        Post.post_id.in_(post_ids),
        Post.tenant_id == tenant_id
    ).all()
    
    found_post_ids = {post.post_id for post in posts}
    missing_ids = set(post_ids) - found_post_ids
    
    if missing_ids:
        return jsonify({
            "error": "Some posts not found or access denied",
            "missing_post_ids": list(missing_ids)
        }), 404
    
    # Import here to avoid circular imports
    from app.tasks.ai_analyzer import analyze_post
    from app.models.job import Job
    from datetime import datetime
    import uuid
    
    # Queue tasks for all posts
    try:
        job_results = []
        for post_id in post_ids:
            # Create job record for each post
            job_id = str(uuid.uuid4())
            job = Job(
                job_id=job_id,
                tenant_id=tenant_id,
                job_type='post_analyze',
                status='pending',
                total_items=1
            )
            db.session.add(job)
            
            try:
                task = analyze_post.delay(job_id, tenant_id, post_id)
                job_results.append({
                    "post_id": post_id,
                    "job_id": job_id
                })
            except Exception as celery_error:
                # Handle Celery connection errors for this specific job
                error_msg = str(celery_error)
                job.status = 'failed'
                job.error_message = f"Celery/Redis connection failed: {error_msg}"
                job.completed_at = datetime.utcnow()
                job_results.append({
                    "post_id": post_id,
                    "job_id": job_id,
                    "error": "Failed to queue task"
                })
        
        db.session.commit()
        current_app.logger.info(f"Post analyze batch: Started {len(job_results)} jobs")
        
        # Check if any jobs failed to queue
        failed_count = sum(1 for j in job_results if 'error' in j)
        if failed_count > 0:
            return jsonify({
                "error": "Some jobs failed to queue",
                "job_ids": [j["job_id"] for j in job_results],
                "posts": job_results,
                "count": len(job_results),
                "failed_count": failed_count,
                "status": "partial"
            }), 207  # Multi-Status
        
        return jsonify({
            "message": "Analysis jobs started",
            "job_ids": [j["job_id"] for j in job_results],
            "posts": job_results,
            "count": len(job_results),
            "status": "queued"
        }), 202
    except Exception as celery_error:
        # Handle Celery connection errors specifically
        error_msg = str(celery_error)
        db.session.rollback()
        if 'Redis' in error_msg or 'broker' in error_msg.lower() or 'connection' in error_msg.lower():
            current_app.logger.error(f"Post analyze batch: Celery/Redis connection error: {error_msg}")
            return jsonify({
                "error": "Celery/Redis connection failed",
                "details": error_msg,
                "message": "Please ensure Redis is running and accessible. Check that the Celery worker is also running."
            }), 503
        else:
            # Re-raise other errors
            current_app.logger.exception(f"Post analyze batch: Unexpected error: {error_msg}")
            return jsonify({
                "error": "Failed to start analysis jobs",
                "details": error_msg
            }), 500


@bp.route('/bulk', methods=['DELETE'])
@jwt_required()
def bulk_delete_posts():
    """
    Bulk delete multiple posts.
    
    Request body:
        {
            "ids": ["uuid1", "uuid2", ...]
        }
    
    Returns:
        - 200 OK: All posts deleted successfully
        - 207 Multi-Status: Partial success (some deleted, some failed)
        - 400 Bad Request: Invalid input or all deletions failed
    
    Validation:
        - Maximum 100 items per request
        - All IDs must belong to the requesting tenant
        - Cannot delete posts linked to campaigns
        - Cannot delete posts with sent emails
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Bulk delete posts: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Bulk delete posts: Request for tenant_id={tenant_id}")
    
    # Parse request body
    data = request.get_json() or {}
    post_ids = data.get('ids', [])
    
    # Validate input
    if not isinstance(post_ids, list):
        current_app.logger.warning(f"Bulk delete posts: Invalid input type, expected list, got {type(post_ids)}")
        return jsonify({"error": "ids must be an array"}), 400
    
    if len(post_ids) == 0:
        current_app.logger.warning("Bulk delete posts: Empty ids array")
        return jsonify({"error": "ids array cannot be empty"}), 400
    
    if len(post_ids) > 100:
        current_app.logger.warning(f"Bulk delete posts: Too many items, got {len(post_ids)}, max 100")
        return jsonify({"error": "Cannot delete more than 100 posts at once"}), 400
    
    current_app.logger.debug(f"Bulk delete posts: Processing {len(post_ids)} post IDs")
    
    # Import models here to avoid circular imports
    from app.models.campaign import Campaign
    from app.models.email import Email
    
    # Track results
    successful = []
    failed = []
    
    try:
        # Fetch all posts that belong to the tenant
        posts = Post.query.filter(
            Post.post_id.in_(post_ids),
            Post.tenant_id == tenant_id
        ).all()
        
        found_post_ids = {post.post_id for post in posts}
        missing_ids = set(post_ids) - found_post_ids
        
        # Add missing IDs to failed list
        for missing_id in missing_ids:
            failed.append({
                "id": missing_id,
                "reason": "Post not found or does not belong to tenant"
            })
            current_app.logger.debug(f"Bulk delete posts: Post {missing_id} not found or access denied")
        
        # Check each post for validation rules
        for post in posts:
            post_id = post.post_id
            current_app.logger.debug(f"Bulk delete posts: Validating post_id={post_id}")
            
            # Check if post is linked to campaigns (prevent deletion if linked)
            campaigns = Campaign.query.filter_by(post_id=post_id).all()
            if campaigns:
                # Check if any linked campaigns have sent emails
                campaign_ids = [campaign.campaign_id for campaign in campaigns]
                from app.models.campaign import CampaignProfile
                
                # Get all campaign profiles for these campaigns
                campaign_profiles = CampaignProfile.query.filter(
                    CampaignProfile.campaign_id.in_(campaign_ids)
                ).all()
                
                # Check if any have sent emails
                email_ids = [cp.email_id for cp in campaign_profiles if cp.email_id]
                if email_ids:
                    sent_emails_count = Email.query.filter(
                        Email.email_id.in_(email_ids),
                        Email.status == 'sent'
                    ).count()
                    
                    if sent_emails_count > 0:
                        failed.append({
                            "id": post_id,
                            "reason": "Post is linked to campaigns with sent emails"
                        })
                        current_app.logger.debug(f"Bulk delete posts: Post {post_id} has {sent_emails_count} sent emails in campaigns")
                        continue
                
                # Post is linked to campaigns (even without sent emails) - prevent deletion
                failed.append({
                    "id": post_id,
                    "reason": "Post is linked to campaigns"
                })
                current_app.logger.debug(f"Bulk delete posts: Post {post_id} is linked to campaigns")
                continue
            
            # Check for direct sent emails (not through campaigns)
            direct_sent_emails = Email.query.filter_by(
                post_id=post_id,
                status='sent'
            ).first()
            
            if direct_sent_emails:
                failed.append({
                    "id": post_id,
                    "reason": "Post has sent emails"
                })
                current_app.logger.debug(f"Bulk delete posts: Post {post_id} has direct sent emails")
                continue
            
            # Post is safe to delete
            try:
                db.session.delete(post)
                successful.append({
                    "id": post_id
                })
                current_app.logger.debug(f"Bulk delete posts: Post {post_id} marked for deletion")
            except Exception as delete_error:
                current_app.logger.error(f"Bulk delete posts: Error deleting post {post_id}: {str(delete_error)}")
                failed.append({
                    "id": post_id,
                    "reason": f"Database error: {str(delete_error)}"
                })
        
        # Commit all deletions
        if successful:
            try:
                db.session.commit()
                current_app.logger.info(f"Bulk delete posts: Successfully deleted {len(successful)} posts")
            except Exception as commit_error:
                current_app.logger.error(f"Bulk delete posts: Error committing deletions: {str(commit_error)}")
                db.session.rollback()
                # Mark all successful as failed due to commit error
                for item in successful:
                    failed.append({
                        "id": item["id"],
                        "reason": f"Commit error: {str(commit_error)}"
                    })
                successful = []
        
        # Determine response status
        if len(failed) == 0:
            # All succeeded
            current_app.logger.info(f"Bulk delete posts: All {len(successful)} posts deleted successfully")
            return jsonify({
                "message": "All posts deleted successfully",
                "deleted_count": len(successful),
                "results": {
                    "successful": successful,
                    "failed": []
                }
            }), 200
        elif len(successful) == 0:
            # All failed
            current_app.logger.warning(f"Bulk delete posts: All {len(failed)} posts failed to delete")
            return jsonify({
                "error": "All deletions failed",
                "deleted_count": 0,
                "results": {
                    "successful": [],
                    "failed": failed
                }
            }), 400
        else:
            # Partial success
            current_app.logger.info(f"Bulk delete posts: Partial success - {len(successful)} deleted, {len(failed)} failed")
            return jsonify({
                "message": "Partial success",
                "deleted_count": len(successful),
                "failed_count": len(failed),
                "results": {
                    "successful": successful,
                    "failed": failed
                }
            }), 207  # Multi-Status
            
    except Exception as e:
        current_app.logger.exception(f"Bulk delete posts: Unexpected error: {str(e)}")
        db.session.rollback()
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500


@bp.route('/<post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    """
    Delete a post by ID.
    
    Requirements:
    - Post must exist and belong to the requesting tenant
    - Post must not be linked to any campaigns
    - Post must not have any sent emails (status='sent')
    - Draft emails will be deleted via CASCADE
    
    Returns:
    - 200: Post deleted successfully
    - 400: Post is linked to campaigns or has sent emails
    - 403: Post belongs to different tenant
    - 404: Post not found
    - 500: Database error
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        current_app.logger.warning("Delete post: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Delete post: Request for post_id={post_id}, tenant_id={tenant_id}")
    
    try:
        # Verify post exists
        post = Post.query.filter_by(post_id=post_id).first()
        
        if not post:
            current_app.logger.warning(f"Delete post: Post not found post_id={post_id}, tenant_id={tenant_id}")
            return jsonify({"error": "Post not found"}), 404
        
        # Verify post belongs to requesting tenant
        if post.tenant_id != tenant_id:
            current_app.logger.warning(
                f"Delete post: Forbidden - post belongs to different tenant. "
                f"post_id={post_id}, post_tenant_id={post.tenant_id}, requesting_tenant_id={tenant_id}"
            )
            return jsonify({"error": "Forbidden"}), 403
        
        current_app.logger.debug(
            f"Delete post: Post found post_id={post_id}, "
            f"company_id={post.company_id}, tenant_id={tenant_id}"
        )
        
        # Check if post is linked to any campaigns
        linked_campaigns = Campaign.query.filter_by(post_id=post_id).all()
        
        if linked_campaigns:
            campaign_ids = [campaign.campaign_id for campaign in linked_campaigns]
            current_app.logger.warning(
                f"Delete post: Cannot delete - post is linked to campaigns. "
                f"post_id={post_id}, campaign_ids={campaign_ids}, tenant_id={tenant_id}"
            )
            return jsonify({
                "error": "Cannot delete post: post is linked to active campaigns. Delete campaigns first."
            }), 400
        
        current_app.logger.debug(f"Delete post: No campaign links found for post_id={post_id}")
        
        # Check if post has any sent emails (status='sent')
        sent_emails = Email.query.filter_by(
            post_id=post_id,
            status='sent'
        ).count()
        
        if sent_emails > 0:
            current_app.logger.warning(
                f"Delete post: Cannot delete - post has sent emails. "
                f"post_id={post_id}, sent_emails_count={sent_emails}, tenant_id={tenant_id}"
            )
            return jsonify({
                "error": "Cannot delete post: post has sent emails associated with it"
            }), 400
        
        # Check for draft emails and delete them explicitly before deleting the post
        # This prevents SQLAlchemy from trying to set post_id to NULL (which violates NOT NULL constraint)
        draft_emails = Email.query.filter_by(
            post_id=post_id,
            status='draft'
        ).all()
        
        draft_emails_count = len(draft_emails)
        
        if draft_emails_count > 0:
            current_app.logger.debug(
                f"Delete post: Found {draft_emails_count} draft email(s) linked to post_id={post_id}. "
                f"Deleting them explicitly before deleting the post"
            )
            # Explicitly delete draft emails to avoid foreign key constraint issues
            for email in draft_emails:
                db.session.delete(email)
        
        # Delete the post (Campaigns will be CASCADE deleted automatically)
        post_source_url = post.source_url
        post_company_id = post.company_id
        
        db.session.delete(post)
        db.session.commit()
        
        current_app.logger.info(
            f"Delete post: Successfully deleted post. "
            f"post_id={post_id}, company_id={post_company_id}, "
            f"source_url={post_source_url[:100] if post_source_url else 'N/A'}..., "
            f"tenant_id={tenant_id}, draft_emails_deleted={draft_emails_count}"
        )
        
        return jsonify({"message": "Post deleted successfully"}), 200
        
    except Exception as e:
        current_app.logger.exception(
            f"Delete post: Error deleting post_id={post_id}, tenant_id={tenant_id}: {str(e)}"
        )
        db.session.rollback()
        return jsonify({
            "error": "Failed to delete post",
            "details": str(e)
        }), 500
