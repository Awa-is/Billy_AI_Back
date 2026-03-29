"""
Email Generation Service - Uses Claude API to generate personalized emails
"""
import logging
import time
from typing import Optional, Dict
from anthropic import Anthropic
from app.extensions import db
from app.models.email import Email
from app.models.email_template import EmailTemplate
from app.models.post import Post
from app.models.profile import Profile
from app.models.company import Company
from app.models.campaign import CampaignProfile

logger = logging.getLogger(__name__)

# Cache for working model (to avoid trying all models on every call)
_working_model_cache = None


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
    global _working_model_cache
    from app.config import Config
    
    # If a model failed, clear cache and find a new one
    if failed_model:
        _working_model_cache = None
        # Find the index of the failed model and start from the next one
        try:
            failed_index = Config.CLAUDE_MODELS.index(failed_model)
            models_to_try = Config.CLAUDE_MODELS[failed_index + 1:]
        except ValueError:
            models_to_try = Config.CLAUDE_MODELS
    else:
        # Return cached model if available
        if _working_model_cache:
            return _working_model_cache
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
            _working_model_cache = model_name
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


def extract_first_name(full_name: Optional[str]) -> str:
    """Extract first name from full name."""
    if not full_name:
        return "there"
    return full_name.split()[0] if full_name.split() else "there"


def build_claude_prompt(post: Post, profile: Profile, template: EmailTemplate, sender_name: str) -> str:
    """
    Build the prompt for Claude API to generate personalized email.
    """
    company_name = post.company.name if post.company else "the company"
    post_text = post.post_text or ""
    recipient_name = extract_first_name(profile.person_name)
    headline = profile.headline or ""
    
    prompt = f"""You are an expert SDR (Sales Development Representative) writing a high-converting cold email.

Given:
- LinkedIn Post: {post_text}
- Recipient: {profile.person_name or 'Recipient'} ({headline})
- Company: {company_name}
- Template Structure:
  Subject: {template.subject}
  Body: {template.body}

Your Goal:
Write a personalized email that feels like it was written by a human, not an AI.
- The opening should be conversational and directly reference the post in a natural way.
- Connect the post content to the recipient's role or company goals.
- Keep it concise and value-focused.

Template placeholders to fill:
- {{recipient_name}} → Use first name only: {recipient_name}
- {{company_name}} → {company_name}
- {{product_name}} → Extract from post
- {{sender_name}} → {sender_name}
- {{post_summary}} → Write a 1-2 sentence conversational opening about the post (e.g., "Loved your thoughts on X...", "Saw your post about Y...")

Output format (JSON):
{{
  "product_name": "extracted product name",
  "post_summary": "Conversational opening sentence(s) about the post",
  "subject": "final subject with all placeholders replaced",
  "body": "final body with all placeholders replaced"
}}

Guidelines for Tone and Style:
- straightforward and professional but conversational (no "I hope this email finds you well")
- Focus on the "so what?" - why does this matter to them?
- Keep paragraphs short (1-2 sentences max).
- Avoid robotic labeling or over-summarizing.

Generate the email now:"""

    return prompt


def call_claude_api(prompt: str, max_retries: int = 3) -> Dict:
    """
    Call Claude API with retry logic for timeouts and rate limits.
    """
    from app.config import Config
    import os
    import json
    
    api_key = os.getenv('CLAUDE_API_KEY')
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not set in environment")
    
    client = Anthropic(api_key=api_key)
    
    from app.config import Config
    working_model = get_working_claude_model(client)
    
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=working_model,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            # Extract text from response
            content = response.content[0].text if response.content else ""
            
            # Parse JSON from Claude's response
            # Claude might wrap JSON in markdown code blocks
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            
            result = json.loads(content)
            
            # Log token usage
            usage = getattr(response, 'usage', None)
            input_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
            output_tokens = getattr(usage, 'output_tokens', 0) if usage else 0
            
            logger.info("Claude API call successful", extra={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempt": attempt + 1,
                "model": working_model
            })
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            error_msg_lower = error_msg.lower()
            
            # If it's a 404 (model not found), try next model
            if "404" in error_msg or "not_found" in error_msg_lower or "model not found" in error_msg_lower:
                logger.warning(f"Model {working_model} not found, trying next available model...")
                try:
                    working_model = get_working_claude_model(client, failed_model=working_model)
                    # Retry immediately with new model (don't count as attempt)
                    continue
                except Exception as fallback_error:
                    logger.error(f"All Claude models failed: {fallback_error}")
                    raise ValueError(f"All configured models failed: {str(fallback_error)}")
            
            logger.warning(f"Claude API call failed (attempt {attempt + 1}/{max_retries})", extra={
                "error": error_msg,
                "attempt": attempt + 1,
                "model": working_model
            })
            
            # Check for rate limit
            if "rate limit" in error_msg_lower or "429" in error_msg:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.info(f"Rate limit hit, waiting {wait_time} seconds")
                time.sleep(wait_time)
                continue
            
            # Check for timeout
            if "timeout" in error_msg_lower or attempt < max_retries - 1:
                wait_time = (attempt + 1) * 1
                time.sleep(wait_time)
                continue
            
            # Last attempt failed
            raise


def generate_email_record(
    tenant_id: str,
    post: Post,
    profile: Profile,
    template: EmailTemplate,
    sender_name: str,
    campaign_id: Optional[str] = None
) -> Email:
    """
    Generate a personalized email using Claude API and save to database.
    
    Returns:
        Email: The created email record
    """
    try:
        # Build Claude prompt
        prompt = build_claude_prompt(post, profile, template, sender_name)
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract values from Claude response
        product_name = str(claude_response.get('product_name', '')).strip()
        post_summary = str(claude_response.get('post_summary', '')).strip()
        subject = str(claude_response.get('subject', template.subject)).strip()
        body = str(claude_response.get('body', template.body)).strip()
        
        # Fallback: if Claude didn't provide subject/body, do manual replacement
        if subject == template.subject or body == template.body:
            # Manual placeholder replacement as fallback
            company_name = post.company.name if post.company else "the company"
            recipient_name = extract_first_name(profile.person_name)
            
            replacements = {
                'recipient_name': recipient_name,
                'company_name': company_name,
                'product_name': product_name or 'the product',
                'sender_name': sender_name,
                'post_summary': post_summary
            }
            
            # Replace in subject
            for key, value in replacements.items():
                subject = subject.replace(f'{{{{{key}}}}}', str(value))
            
            # Replace in body
            for key, value in replacements.items():
                body = body.replace(f'{{{{{key}}}}}', str(value))
        
        # Create email record
        email = Email(
            tenant_id=tenant_id,
            post_id=post.post_id,
            profile_id=profile.profile_id,
            template_id=template.template_id,
            subject=subject,
            body=body,
            status='draft'
        )
        
        db.session.add(email)
        db.session.flush()  # Get email_id
        
        # If profile is in a campaign, update campaign_profiles
        if campaign_id:
            campaign_profile = CampaignProfile.query.filter_by(
                campaign_id=campaign_id,
                profile_id=profile.profile_id
            ).first()
            
            if campaign_profile:
                campaign_profile.email_id = email.email_id
                campaign_profile.status = 'email_generated'
        
        db.session.commit()
        
        logger.info("Email generated successfully", extra={
            "email_id": email.email_id,
            "post_id": post.post_id,
            "profile_id": profile.profile_id,
            "campaign_id": campaign_id
        })
        
        return email
        
    except Exception as e:
        logger.exception("Failed to generate email", extra={
            "post_id": post.post_id,
            "profile_id": profile.profile_id,
            "error": str(e)
        })
        db.session.rollback()
        raise

