"""
Email Draft Generation from Signals

Generates email drafts automatically from detected signals.
Includes signal context, AI instructions, and personalization.
"""

from typing import Optional, Dict, Any
from app.extensions import db
from app.models.signal import Signal
from app.models.email import Email
from app.models.post import Post
from app.models.profile import Profile
from app.models.company import Company
from app.models.email_template import EmailTemplate
from app.models.tenant_setting import TenantSetting
from app.services.email_generation import build_claude_prompt, call_claude_api, extract_first_name
from anthropic import Anthropic
import logging
import json
import os

logger = logging.getLogger(__name__)


def get_ai_instructions(tenant_id: str) -> Optional[str]:
    """Get AI instructions for email generation from tenant settings."""
    setting = TenantSetting.query.filter_by(
        tenant_id=tenant_id,
        key='ai_email_instructions'
    ).first()
    
    return setting.value if setting else None


def get_default_template(tenant_id: str) -> Optional[EmailTemplate]:
    """Get default email template for tenant."""
    # First try to get tenant's default template
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


def build_signal_email_prompt(
    signal: Signal,
    profile: Profile,
    template: EmailTemplate,
    sender_name: str,
    ai_instructions: Optional[str] = None
) -> str:
    """
    Build prompt for Claude to generate email from signal.
    
    Includes:
    - Signal context (type, post, company)
    - AI instructions (if set)
    - Profile information for personalization
    """
    company_name = signal.company.name if signal.company else "the company"
    post_text = signal.post.post_text if signal.post else ""
    recipient_name = extract_first_name(profile.person_name)
    headline = profile.headline or ""
    about = profile.about or ""
    job_title = profile.job_title or ""
    industry = profile.industry or profile.company_industry or ""
    
    # Build signal context
    signal_context = f"""
Signal Type: {signal.signal_type}
Signal Score: {signal.score}/100
Company: {company_name}
Post: {post_text[:500] if post_text else 'N/A'}
"""
    
    if signal.keywords:
        signal_context += f"Keywords: {signal.keywords}\n"
    
    # Build instructions section
    instructions_section = ""
    if ai_instructions:
        instructions_section = f"""
Additional Instructions:
{ai_instructions}
"""
    
    prompt = f"""You are an expert SDR (Sales Development Representative) writing a high-converting cold email.

Given Signal Context:
{signal_context}

Recipient Information:
- Name: {profile.person_name or 'Recipient'}
- Job Title: {job_title}
- Headline: {headline}
- Company: {profile.company_name or 'N/A'}
- Industry: {industry}
- Bio/About: {about[:1000] if about else 'N/A'}

Template Structure:
  Subject: {template.subject}
  Body: {template.body}
{instructions_section}

Your Goal:
Write a personalized email that feels like it was written by a human, not an AI.
- The opening should be conversational and directly reference the signal (news/launch) in a natural way.
- Connect the signal to the recipient's role or company goals.
- Keep it concise and value-focused.

Template placeholders to fill:
- {{recipient_name}} → Use first name only: {recipient_name}
- {{company_name}} → {company_name}
- {{product_name}} → Extract from signal context
- {{sender_name}} → {sender_name}
- {{post_summary}} → Write a 1-2 sentence conversational opening about the signal (e.g., "Saw the news about X...", "Congrats on the launch of Y...")

Output format (JSON):
{{
  "product_name": "extracted product name or signal topic",
  "post_summary": "Conversational opening sentence(s) about the signal",
  "subject": "final subject with all placeholders replaced",
  "body": "final body with all placeholders replaced"
}}

Guidelines for Tone and Style:
- straightforward and professional but conversational (no "I hope this email finds you well")
- Focus on the "so what?" - why does this news matter to them?
- Keep paragraphs short (1-2 sentences max).
- Avoid robotic labeling or over-summarizing.

"""
    
    return prompt


class SimpleTemplate:
    """Fallback template when no DB template exists."""
    def __init__(self, subject: str, body: str):
        self.subject = subject
        self.body = body
        self.template_id = None

# ... key imports are already there ...

def generate_email_from_signal(
    signal: Signal,
    profile: Profile,
    tenant_id: str,
    sender_name: str = "Team"
) -> Optional[Email]:
    """
    Generate email draft from a detected signal.
    
    Args:
        signal: Signal object
        profile: Profile to send email to
        tenant_id: Tenant ID
        sender_name: Name of sender
        
    Returns:
        Email object if successful, None otherwise
    """
    try:
        # Validate signal belongs to tenant
        if signal.tenant_id != tenant_id:
            logger.error(f"Signal {signal.signal_id} does not belong to tenant {tenant_id}")
            return None
        
        # Check if email already exists for this signal+profile
        existing_email = Email.query.filter_by(
            tenant_id=tenant_id,
            signal_id=signal.signal_id,
            profile_id=profile.profile_id
        ).first()
        
        if existing_email:
            logger.debug(f"Email already exists for signal {signal.signal_id} and profile {profile.profile_id}")
            return existing_email
        
        # Get template (Profile preference > Tenant Default > System Default)
        template = None
        if profile.assigned_template_id:
            template = EmailTemplate.query.get(profile.assigned_template_id)
            if template and template.tenant_id != tenant_id and not template.is_default:
                # Security check: ensure template belongs to tenant or is system default
                template = None
        
        if not template:
            template = get_default_template(tenant_id)
            
        if not template:
            logger.error(f"No email template found for tenant {tenant_id}")
            return None
        
        # Get AI instructions
        ai_instructions = get_ai_instructions(tenant_id)
        
        # Get post (required for email)
        post = signal.post
        if not post:
            logger.error(f"Signal {signal.signal_id} has no associated post")
            return None
        
        # Build prompt
        prompt = build_signal_email_prompt(
            signal=signal,
            profile=profile,
            template=template,
            sender_name=sender_name,
            ai_instructions=ai_instructions
        )
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract values
        product_name = str(claude_response.get('product_name', '')).strip()
        post_summary = str(claude_response.get('post_summary', '')).strip()
        subject = str(claude_response.get('subject', template.subject)).strip()
        body = str(claude_response.get('body', template.body)).strip()
        
        # Fallback: manual replacement if Claude didn't provide
        if subject == template.subject or body == template.body:
            company_name = signal.company.name if signal.company else "the company"
            recipient_name = extract_first_name(profile.person_name)
            
            replacements = {
                'recipient_name': recipient_name,
                'company_name': company_name,
                'product_name': product_name or 'the product',
                'sender_name': sender_name,
                'post_summary': post_summary
            }
            
            for key, value in replacements.items():
                subject = subject.replace(f'{{{{{key}}}}}', str(value))
                body = body.replace(f'{{{{{key}}}}}', str(value))
        
        # Create email record
        email = Email(
            tenant_id=tenant_id,
            post_id=post.post_id,
            profile_id=profile.profile_id,
            template_id=template.template_id,
            signal_id=signal.signal_id,
            subject=subject,
            body=body,
            status='draft',
            approval_status='pending'
        )
        
        db.session.add(email)
        db.session.commit()
        
        logger.info(f"Email draft generated from signal: email_id={email.email_id}, signal_id={signal.signal_id}, profile_id={profile.profile_id}")
        
        return email
        
    except Exception as e:
        logger.exception(f"Failed to generate email from signal {signal.signal_id}: {e}")
        db.session.rollback()
        return None


def generate_emails_for_signal(
    signal: Signal,
    tenant_id: str,
    sender_name: str = "Team",
    profile_ids: Optional[list] = None
) -> int:
    """
    Generate email drafts for all relevant profiles for a signal.
    
    Args:
        signal: Signal object
        tenant_id: Tenant ID
        sender_name: Name of sender
        profile_ids: Optional list of profile IDs to generate for (if None, uses all profiles with emails)
        
    Returns:
        Number of emails generated
    """
    try:
        # Get profiles to generate emails for
        if profile_ids:
            profiles = Profile.query.filter(
                Profile.tenant_id == tenant_id,
                Profile.profile_id.in_(profile_ids),
                Profile.email.isnot(None),
                Profile.email != ''
            ).all()
        else:
            # Get all profiles with emails for this tenant
            profiles = Profile.query.filter(
                Profile.tenant_id == tenant_id,
                Profile.email.isnot(None),
                Profile.email != ''
            ).all()
        
        if not profiles:
            logger.warning(f"No profiles with emails found for tenant {tenant_id}")
            return 0
        
        generated_count = 0
        for profile in profiles:
            email = generate_email_from_signal(
                signal=signal,
                profile=profile,
                tenant_id=tenant_id,
                sender_name=sender_name
            )
            if email:
                generated_count += 1
        
        logger.info(f"Generated {generated_count} email drafts for signal {signal.signal_id}")
        
        return generated_count
        
    except Exception as e:
        logger.exception(f"Failed to generate emails for signal {signal.signal_id}: {e}")
        return 0


