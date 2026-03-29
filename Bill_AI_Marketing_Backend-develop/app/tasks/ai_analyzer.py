"""
Celery task for analyzing LinkedIn posts using Claude AI
"""
import os
import logging
from datetime import datetime
from anthropic import Anthropic
from app.tasks.celery_app import celery_app
from app.extensions import db
from app.models.post import Post
from app.models.job import Job
from app import create_app
from app.config import Config

logger = logging.getLogger(__name__)

# Initialize Anthropic client
anthropic_client = None
# Cache for working model (to avoid trying all models on every call)
_working_model = None


def get_anthropic_client():
    """Get or create Anthropic client"""
    global anthropic_client
    if anthropic_client is None:
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError("CLAUDE_API_KEY not configured")
        anthropic_client = Anthropic(api_key=api_key)
    return anthropic_client


def get_working_claude_model(client, failed_model=None):
    """
    Get a working Claude model, trying multiple models if needed.
    Caches the working model to avoid repeated API calls.
    
    Args:
        client: Anthropic client instance
        failed_model: If provided, this model failed and we should try the next one
    
    Returns:
        str: The first working model name
    """
    global _working_model
    
    # If a model failed, clear cache and find a new one
    if failed_model:
        _working_model = None
        # Find the index of the failed model and start from the next one
        try:
            failed_index = Config.CLAUDE_MODELS.index(failed_model)
            models_to_try = Config.CLAUDE_MODELS[failed_index + 1:]
        except ValueError:
            models_to_try = Config.CLAUDE_MODELS
    else:
        # Return cached model if available
        if _working_model:
            return _working_model
        models_to_try = Config.CLAUDE_MODELS
    
    # Try each model in order
    for model_name in models_to_try:
        try:
            # Test the model with a minimal request
            test_response = client.messages.create(
                model=model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "test"}]
            )
            # If successful, cache and return this model
            _working_model = model_name
            logger.info(f"Using Claude model: {model_name}")
            return model_name
        except Exception as e:
            error_str = str(e).lower()
            # If it's a 404 (model not found), try next model
            if "404" in error_str or "not_found" in error_str or "model not found" in error_str:
                logger.warning(f"Model {model_name} not available, trying next...")
                continue
            # For other errors (auth, etc.), don't try other models
            logger.error(f"Error testing model {model_name}: {e}")
            raise
    
    # If all models failed, raise error
    raise ValueError(f"None of the configured Claude models are available: {Config.CLAUDE_MODELS}")


@celery_app.task(bind=True, max_retries=3)
def analyze_post(self, job_id, tenant_id, post_id):
    """
    Analyze a LinkedIn post using Claude AI to detect product launches.
    
    Args:
        job_id: UUID of the job tracking this task
        tenant_id: UUID of the tenant
        post_id: UUID of the post to analyze
        
    Returns:
        dict: Analysis result with score and judgement
    """
    app = create_app()
    
    with app.app_context():
        job = None
        try:
            # Get job record
            job = Job.query.filter_by(job_id=job_id).first()
            if not job:
                logger.error(f"Job not found: {job_id}")
                return {"status": "error", "message": "Job not found"}
            
            # Update job status to processing
            job.status = 'processing'
            job.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Post analysis job started: job_id={job_id}, post_id={post_id}")
            
            # Get post from database
            post = Post.query.filter_by(post_id=post_id, tenant_id=tenant_id).first()
            if not post:
                logger.error(f"Post {post_id} not found")
                job.status = 'failed'
                job.error_message = f"Post not found: {post_id}"
                job.completed_at = datetime.utcnow()
                job.completed_items = 1
                job.failed_count = 1
                db.session.commit()
                return {"error": "Post not found", "post_id": post_id}
            
            if not post.post_text:
                logger.warning(f"Post {post_id} has no text to analyze")
                # Update with default values
                post.score = 0
                post.ai_judgement = 'other'
                post.analyzed_at = datetime.utcnow()
                job.status = 'completed'
                job.completed_at = datetime.utcnow()
                job.completed_items = 1
                job.success_count = 1
                job.updated_at = datetime.utcnow()
                db.session.commit()
                return {"error": "Post has no text", "post_id": post_id}
            
            # Prepare prompt for Claude
            prompt = f"""Analyze this LinkedIn post and determine if it contains signals for sales outreach.

Signal types to detect:
- product_launch: New product announcement or launch
- company_news: Company news, updates, milestones, achievements
- other: No relevant signal

Score 0-100 based on relevance for B2B sales outreach.

Return JSON format:
{{"score": X, "judgement": "product_launch"|"company_news"|"other"}}

Post text:
{post.post_text}

Analyze and return JSON only:"""
            
            # Call Claude API
            client = get_anthropic_client()
            
            # Get working model (uses cache if available)
            working_model = get_working_claude_model(client)
            
            try:
                message = client.messages.create(
                    model=working_model,
                    max_tokens=Config.CLAUDE_MAX_TOKENS,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                
                # Extract response text
                response_text = message.content[0].text.strip()
                
                # Parse JSON response
                import json
                # Try to extract JSON from response (handle markdown code blocks)
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                
                analysis = json.loads(response_text)
                
                # Validate response structure
                score = int(analysis.get('score', 0))
                judgement = analysis.get('judgement', 'other')
                
                # Validate judgement is one of the allowed types
                if judgement not in ['product_launch', 'company_news', 'other']:
                    judgement = 'other'
                
                # Clamp score to 0-100
                score = max(0, min(100, score))
                
                # Update post
                post.score = score
                post.ai_judgement = judgement
                post.analyzed_at = datetime.utcnow()
                
                # Update job status to completed
                job.status = 'completed'
                job.completed_at = datetime.utcnow()
                job.completed_items = 1
                job.success_count = 1
                job.updated_at = datetime.utcnow()
                
                # Store result data
                result_data = {
                    "post_id": post_id,
                    "score": score,
                    "judgement": judgement,
                    "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
                }
                job.result_data = json.dumps(result_data)
                
                db.session.commit()
                
                logger.info(f"Successfully analyzed post {post_id}: score={score}, judgement={judgement}")
                
                # Trigger signal detection if judgement is a signal type
                if judgement in ['product_launch', 'company_news'] and score >= 80:
                    try:
                        from app.tasks.signal_tasks import process_signals_and_emails_task
                        # Queue signal detection and email generation (async)
                        process_signals_and_emails_task.delay(tenant_id)
                        logger.info(f"Queued signal detection for tenant {tenant_id} after post analysis")
                    except Exception as signal_error:
                        logger.warning(f"Failed to queue signal detection: {signal_error}")
                        # Don't fail the analysis task if signal detection fails
                
                return {
                    "status": "success",
                    "post_id": post_id,
                    "score": score,
                    "judgement": judgement,
                    "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
                }
                
            except Exception as api_error:
                error_str = str(api_error)
                error_msg_lower = error_str.lower()
                logger.error(f"Claude API error for post {post_id}: {error_str}")
                
                # Check for non-retryable errors (fail immediately)
                # 404 = model not found, invalid model name
                # 400 = bad request, invalid parameters
                # 401 = unauthorized, invalid API key
                # 403 = forbidden
                non_retryable_errors = [
                    "404", "not_found", "model not found", "invalid model",
                    "400", "bad request", "invalid",
                    "401", "unauthorized", "invalid api key",
                    "403", "forbidden"
                ]
                
                is_non_retryable = any(err in error_msg_lower for err in non_retryable_errors)
                
                # If it's a 404 (model not found), try next model
                if "404" in error_str or "not_found" in error_msg_lower or "model not found" in error_msg_lower:
                    logger.warning(f"Model {working_model} not found, trying next available model...")
                    try:
                        # Try next model
                        working_model = get_working_claude_model(client, failed_model=working_model)
                        # Retry with new model (don't count as a retry)
                        message = client.messages.create(
                            model=working_model,
                            max_tokens=Config.CLAUDE_MAX_TOKENS,
                            messages=[
                                {"role": "user", "content": prompt}
                            ]
                        )
                        # If successful, continue with processing
                        response_text = message.content[0].text.strip()
                        # Parse JSON response
                        import json
                        if "```json" in response_text:
                            response_text = response_text.split("```json")[1].split("```")[0].strip()
                        elif "```" in response_text:
                            response_text = response_text.split("```")[1].split("```")[0].strip()
                        
                        analysis = json.loads(response_text)
                        score = int(analysis.get('score', 0))
                        judgement = analysis.get('judgement', 'other')
                        
                        if judgement not in ['product_launch', 'other']:
                            judgement = 'other'
                        
                        score = max(0, min(100, score))
                        
                        post.score = score
                        post.ai_judgement = judgement
                        post.analyzed_at = datetime.utcnow()
                        
                        job.status = 'completed'
                        job.completed_at = datetime.utcnow()
                        job.completed_items = 1
                        job.success_count = 1
                        job.updated_at = datetime.utcnow()
                        
                        result_data = {
                            "post_id": post_id,
                            "score": score,
                            "judgement": judgement,
                            "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
                        }
                        job.result_data = json.dumps(result_data)
                        
                        db.session.commit()
                        
                        logger.info(f"Successfully analyzed post {post_id} with model {working_model}: score={score}, judgement={judgement}")
                        
                        return {
                            "status": "success",
                            "post_id": post_id,
                            "score": score,
                            "judgement": judgement,
                            "analyzed_at": post.analyzed_at.isoformat() if post.analyzed_at else None
                        }
                    except Exception as fallback_error:
                        # All models failed
                        logger.error(f"All Claude models failed for post {post_id}: {fallback_error}")
                        job.status = 'failed'
                        job.error_message = f"All configured models failed: {str(fallback_error)}"
                        job.completed_at = datetime.utcnow()
                        job.completed_items = 1
                        job.failed_count = 1
                        job.updated_at = datetime.utcnow()
                        
                        post.score = 0
                        post.ai_judgement = 'other'
                        post.analyzed_at = datetime.utcnow()
                        
                        db.session.commit()
                        
                        return {
                            "status": "error",
                            "error": "All Claude models unavailable",
                            "post_id": post_id,
                            "details": str(fallback_error)
                        }
                
                if is_non_retryable:
                    # Fail immediately - don't retry
                    logger.error(f"Non-retryable error for post {post_id}: {error_str}")
                    job.status = 'failed'
                    job.error_message = f"API error (non-retryable): {error_str}"
                    job.completed_at = datetime.utcnow()
                    job.completed_items = 1
                    job.failed_count = 1
                    job.updated_at = datetime.utcnow()
                    
                    # Update post with default values
                    post.score = 0
                    post.ai_judgement = 'other'
                    post.analyzed_at = datetime.utcnow()
                    
                    db.session.commit()
                    
                    return {
                        "status": "error",
                        "error": "Analysis failed - non-retryable error",
                        "post_id": post_id,
                        "details": error_str
                    }
                
                # Handle rate limits with exponential backoff (retryable)
                if "rate limit" in error_msg_lower or "429" in error_str:
                    logger.warning(f"Rate limit hit for post {post_id}, retrying...")
                    raise self.retry(exc=api_error, countdown=60 * (2 ** self.request.retries))
                
                # For other transient errors (5xx, timeouts), retry with backoff
                # Only retry if we haven't exceeded max retries
                if self.request.retries < self.max_retries:
                    logger.warning(f"Transient error for post {post_id}, retrying... (attempt {self.request.retries + 1}/{self.max_retries})")
                    raise self.retry(exc=api_error, countdown=30 * (2 ** self.request.retries))
                else:
                    # Max retries reached, fail the job
                    logger.error(f"Max retries reached for post {post_id}")
                    job.status = 'failed'
                    job.error_message = f"Analysis failed after {self.max_retries} retries: {error_str}"
                    job.completed_at = datetime.utcnow()
                    job.completed_items = 1
                    job.failed_count = 1
                    job.updated_at = datetime.utcnow()
                    
                    # Update post with default values
                    post.score = 0
                    post.ai_judgement = 'other'
                    post.analyzed_at = datetime.utcnow()
                    
                    db.session.commit()
                    
                    return {
                        "status": "error",
                        "error": "Analysis failed after retries",
                        "post_id": post_id,
                        "details": error_str
                    }
            
        except Exception as e:
            logger.error(f"Error analyzing post {post_id}: {str(e)}")
            
            # If max retries reached, mark as failed
            if self.request.retries >= self.max_retries:
                try:
                    if job:
                        job.status = 'failed'
                        job.error_message = f"Analysis failed after retries: {str(e)}"
                        job.completed_at = datetime.utcnow()
                        job.completed_items = 1
                        job.failed_count = 1
                        job.updated_at = datetime.utcnow()
                        db.session.commit()
                    
                    post = Post.query.filter_by(post_id=post_id, tenant_id=tenant_id).first()
                    if post:
                        post.score = 0
                        post.ai_judgement = 'other'
                        post.analyzed_at = datetime.utcnow()
                        db.session.commit()
                except Exception as db_error:
                    logger.error(f"Failed to update post {post_id} after max retries: {str(db_error)}")
                
                return {
                    "status": "error",
                    "error": "Analysis failed after retries",
                    "post_id": post_id,
                    "details": str(e)
                }
            
            raise self.retry(exc=e, countdown=30 * (2 ** self.request.retries))

