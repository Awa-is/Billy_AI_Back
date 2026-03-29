"""
Email Refinement Service - Uses Claude API to refine/improve existing email drafts
"""

import logging
from typing import Optional, Dict, Any
from app.extensions import db
from app.models.email import Email
from app.models.signal import Signal
from app.models.post import Post
from app.models.profile import Profile
from app.models.email_template import EmailTemplate
from app.services.email_generation import call_claude_api, extract_first_name

logger = logging.getLogger(__name__)


def get_ai_instructions(tenant_id: str, user_id: Optional[str] = None) -> Optional[str]:
    """
    Get AI instructions for email generation.
    Priority: user-specific instructions > tenant-level instructions
    
    Args:
        tenant_id: Tenant ID
        user_id: User ID (optional) - if provided, checks user-specific instructions first
        
    Returns:
        AI instructions string or None
    """
    # First check user-specific instructions if user_id provided
    if user_id:
        from app.models.user_setting import UserSetting
        user_setting = UserSetting.query.filter_by(
            user_id=user_id,
            key='ai_email_instructions'
        ).first()
        
        if user_setting and user_setting.value:
            return user_setting.value
    
    # Fallback to tenant-level instructions
    from app.models.tenant_setting import TenantSetting
    setting = TenantSetting.query.filter_by(
        tenant_id=tenant_id,
        key='ai_email_instructions'
    ).first()
    
    return setting.value if setting else None


def get_default_template(tenant_id: str) -> Optional[EmailTemplate]:
    """Get default email template for tenant."""
    # First try to get tenant's template
    template = EmailTemplate.query.filter_by(
        tenant_id=tenant_id,
        is_default=False
    ).order_by(EmailTemplate.created_at.desc()).first()
    
    # Fallback to system default
    if not template:
        template = EmailTemplate.query.filter_by(
            is_default=True
        ).first()
    
    return template


def build_refine_email_prompt(
    email: Email,
    signal: Optional[Signal],
    post: Post,
    profile: Profile,
    template: EmailTemplate,
    sender_name: str,
    ai_instructions: Optional[str] = None,
    refinement_options: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build prompt for Claude to refine/improve an existing email.
    
    Uses the same signal context and instructions as original generation,
    but asks AI to improve the existing email content.
    """
    company_name = post.company.name if post.company else "the company"
    post_text = post.post_text or ""
    recipient_name = extract_first_name(profile.person_name)
    headline = profile.headline or ""
    
    # Build signal context if available
    signal_context = ""
    if signal:
        signal_context = f"""
Signal Context:
- Signal Type: {signal.signal_type}
- Signal Score: {signal.score}/100
- Company: {company_name}
- Post: {post_text[:500] if post_text else 'N/A'}
"""
        if signal.keywords:
            signal_context += f"- Keywords: {signal.keywords}\n"
    
    # Build instructions section
    instructions_section = ""
    if ai_instructions:
        instructions_section = f"""
Additional Instructions:
{ai_instructions}
"""
    
    # Build refinement criteria section based on options
    refinement_criteria = []
    
    if refinement_options:
        # Tone adjustment
        if refinement_options.get('tone'):
            tone = refinement_options['tone']
            refinement_criteria.append(f"- **Tone**: Write in a {tone.lower()} tone")
        
        # Length adjustments
        if refinement_options.get('make_shorter'):
            refinement_criteria.append("- **Length**: Make the email significantly shorter and more concise")
        elif refinement_options.get('make_longer'):
            refinement_criteria.append("- **Length**: Expand the email to provide more detail and context")
        
        # Grammar and spelling
        if refinement_options.get('fix_spelling_grammar'):
            refinement_criteria.append("- **Grammar & Spelling**: Fix all spelling errors, grammatical mistakes, and improve sentence structure")
    
    # Build refinement criteria section
    criteria_section = ""
    if refinement_criteria:
        criteria_section = f"""
Specific Refinement Requirements:
{chr(10).join(refinement_criteria)}
"""
    
    # Build refine prompt
    prompt = f"""You are an expert SDR (Sales Development Representative) refining a cold email.

Current Email to Refine:
Subject: {email.subject}
Body: {email.body}

Context:
{signal_context if signal_context else f"Post: {post_text}\nCompany: {company_name}"}

Recipient Information:
- Name: {profile.person_name or 'Recipient'}
- Headline: {headline}
- Company: {profile.company_name or 'N/A'}

Template Structure (for reference):
  Subject: {template.subject}
  Body: {template.body}
{instructions_section}{criteria_section}

Your Goal:
Improve the email to make it feel more human and less robotic.
- Make the opening more conversational.
- Ensure the connection between the signal and the recipient's goals is clear.
- Remove any "fluff" or overly formal language.

Output format (JSON):
{{
  "subject": "improved subject line",
  "body": "improved email body"
}}

Guidelines for refinement:
- Keep it professional but friendly
- Make it more personalized when possible
- Improve clarity and impact
- Ensure it's natural and conversational (no "I hope this email finds you well")
- Reference the signal context naturally
- Maintain appropriate length (not too long, not too short)

Refine the email now:"""

    return prompt


def build_manual_refine_email_prompt(
    email: Email,
    template: EmailTemplate,
    sender_name: str,
    ai_instructions: Optional[str] = None,
    refinement_options: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build prompt for Claude to refine/improve a manual email (no signal/post context).
    """
    recipient_email = email.recipients or "recipient@example.com"
    recipient_name = extract_first_name(recipient_email.split('@')[0])
    
    # Build instructions section
    instructions_section = ""
    if ai_instructions:
        instructions_section = f"""
Additional Instructions:
{ai_instructions}
"""
    
    # Build refinement criteria section based on options
    refinement_criteria = []
    
    if refinement_options:
        # Tone adjustment
        if refinement_options.get('tone'):
            tone = refinement_options['tone']
            refinement_criteria.append(f"- **Tone**: Write in a {tone.lower()} tone")
        
        # Length adjustments
        if refinement_options.get('make_shorter'):
            refinement_criteria.append("- **Length**: Make the email significantly shorter and more concise")
        elif refinement_options.get('make_longer'):
            refinement_criteria.append("- **Length**: Expand the email to provide more detail and context")
        
        # Grammar and spelling
        if refinement_options.get('fix_spelling_grammar'):
            refinement_criteria.append("- **Grammar & Spelling**: Fix all spelling errors, grammatical mistakes, and improve sentence structure")
    
    # Build refinement criteria section
    criteria_section = ""
    if refinement_criteria:
        criteria_section = f"""
Specific Refinement Requirements:
{chr(10).join(refinement_criteria)}
"""
    
    prompt = f"""You are an AI assistant helping to refine and improve generic B2B outreach emails for sales professionals.

Current Email to Refine:
Subject: {email.subject}
Body: {email.body}

Recipient Information:
- Email: {recipient_email}
- Name: {recipient_name}

Template Structure (for reference):
  Subject: {template.subject}
  Body: {template.body}
{instructions_section}{criteria_section}

Your Goal:
Improve the email to make it feel more human and less robotic.
- Make the opening more conversational.
- Focus on value and relevance to the recipient.
- Remove any "fluff" or overly formal language.

Output format (JSON):
{{
  "subject": "improved subject line",
  "body": "improved email body"
}}

Guidelines for refinement:
- Keep it professional but friendly
- Make it more personalized when possible
- Improve clarity and impact
- Ensure it's natural and conversational (no "I hope this email finds you well")
- Maintains appropriate length (not too long, not too short)
- Focus on value proposition and collaboration

Refine the email now:"""

    return prompt


def refine_email_content(
    email: Email,
    tenant_id: str,
    sender_name: str = "Team",
    user_id: Optional[str] = None,
    refinement_options: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Refine an existing email using AI.
    Handles both signal-based emails and manual emails.
    
    Args:
        email: Email object to refine
        tenant_id: Tenant ID
        sender_name: Name of sender
        
    Returns:
        Dict with 'subject' and 'body' keys containing refined content
    """
    try:
        # Get template
        template = email.template
        if not template:
            # Get default template
            from app.services.signal_email_generation import get_default_template
            template = get_default_template(tenant_id)
            if not template:
                raise ValueError("No email template found")
        
        # Check if this is a manual email (no post_id)
        is_manual = email.post_id is None
        
        if is_manual:
            # Manual email refinement
            ai_instructions = get_ai_instructions(tenant_id, user_id=user_id)
            
            prompt = build_manual_refine_email_prompt(
                email=email,
                template=template,
                sender_name=sender_name,
                ai_instructions=ai_instructions,
                refinement_options=refinement_options
            )
        else:
            # Signal-based email refinement
            post = email.post
            if not post:
                raise ValueError("Email has no associated post")
            
            profile = email.profile
            if not profile:
                raise ValueError("Email has no associated profile")
            
            signal = email.signal
            ai_instructions = get_ai_instructions(tenant_id)
            
            prompt = build_refine_email_prompt(
                email=email,
                signal=signal,
                post=post,
                profile=profile,
                template=template,
                sender_name=sender_name,
                ai_instructions=ai_instructions,
                refinement_options=refinement_options
            )
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract refined content
        refined_subject = str(claude_response.get('subject', email.subject)).strip()
        refined_body = str(claude_response.get('body', email.body)).strip()
        
        logger.info(f"Email refined successfully: email_id={email.email_id}, is_manual={is_manual}")
        
        return {
            "subject": refined_subject,
            "body": refined_body
        }
        
    except Exception as e:
        logger.exception(f"Failed to refine email {email.email_id}: {e}")
        raise
