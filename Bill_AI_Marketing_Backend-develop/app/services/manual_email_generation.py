"""
Service for generating generic emails without signals or posts.
Used for manual email composition.
"""
import logging
from typing import Optional, Dict
from app.extensions import db
from app.models.email import Email
from app.models.email_template import EmailTemplate
from app.models.tenant_setting import TenantSetting
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
    setting = TenantSetting.query.filter_by(
        tenant_id=tenant_id,
        key='ai_email_instructions'
    ).first()
    return setting.value if setting else None


def get_default_template(tenant_id: str) -> Optional[EmailTemplate]:
    """Get default email template for tenant"""
    # Try tenant-specific default first
    template = EmailTemplate.query.filter_by(
        tenant_id=tenant_id,
        is_default=True
    ).first()
    
    # Fallback to system default
    if not template:
        template = EmailTemplate.query.filter_by(
            tenant_id=None,
            is_default=True
        ).first()
    
    return template


def build_manual_email_prompt(
    recipient_email: str,
    recipient_name: Optional[str],
    template: EmailTemplate,
    sender_name: str,
    subject_hint: Optional[str] = None,
    ai_instructions: Optional[str] = None
) -> str:
    """
    Build prompt for Claude API to generate generic outreach email.
    """
    recipient_name_display = recipient_name or extract_first_name(recipient_email.split('@')[0])
    
    instructions_section = ""
    if ai_instructions:
        instructions_section = f"""
Additional Instructions:
{ai_instructions}
"""
    
    subject_hint_section = ""
    if subject_hint:
        subject_hint_section = f"""
Subject Hint (optional): {subject_hint}
"""
    
    prompt = f"""You are an AI assistant helping to generate generic B2B outreach emails for sales professionals.

Recipient Information:
- Email: {recipient_email}
- Name: {recipient_name_display if recipient_name else 'Unknown'}

Template Structure:
  Subject: {template.subject}
  Body: {template.body}
{subject_hint_section}{instructions_section}
Your tasks:
1. Generate a professional, personalized outreach email
2. Fill in all template placeholders with appropriate values
3. Make the email relevant and engaging without specific signal context
4. Keep it concise and professional

Template placeholders to fill:
- {{recipient_name}} → Use first name: {recipient_name_display}
- {{company_name}} → Use recipient's company domain or "your company"
- {{product_name}} → Use a generic product/service reference or "our solution"
- {{sender_name}} → {sender_name}
- {{post_summary}} → Generate 2-3 sentences about potential collaboration/value proposition

Output format (JSON):
{{
  "product_name": "generic product/service reference",
  "post_summary": "2-3 sentence value proposition or collaboration opportunity",
  "subject": "final subject with all placeholders replaced",
  "body": "final body with all placeholders replaced"
}}

Make the email:
- Professional but friendly
- Personalized to the recipient when possible
- Focused on value proposition and collaboration
- Natural and conversational
- 2-3 sentences for post_summary
- Generic enough to work without specific signal context

Generate the email now:"""

    return prompt


def generate_manual_email(
    tenant_id: str,
    recipient_email: str,
    recipient_name: Optional[str] = None,
    subject_hint: Optional[str] = None,
    sender_name: str = "Team",
    user_id: Optional[str] = None
) -> Email:
    """
    Generate a generic email without signal or post context.
    
    Args:
        tenant_id: Tenant ID
        recipient_email: Recipient email address (required)
        recipient_name: Recipient name (optional)
        subject_hint: Optional subject hint
        sender_name: Sender name
        
    Returns:
        Email: The created email record
    """
    try:
        # Get default template
        template = get_default_template(tenant_id)
        if not template:
            raise ValueError("No email template found. Please create a default template.")
        
        # Get AI instructions (user-specific if user_id provided)
        ai_instructions = get_ai_instructions(tenant_id, user_id=user_id)
        
        # Build prompt
        prompt = build_manual_email_prompt(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            template=template,
            sender_name=sender_name,
            subject_hint=subject_hint,
            ai_instructions=ai_instructions
        )
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract values
        product_name = claude_response.get('product_name', 'our solution')
        post_summary = claude_response.get('post_summary', '')
        subject = claude_response.get('subject', template.subject)
        body = claude_response.get('body', template.body)
        
        # Fallback: if Claude didn't provide subject/body, do manual replacement
        if subject == template.subject or body == template.body:
            recipient_name_display = recipient_name or extract_first_name(recipient_email.split('@')[0])
            company_name = recipient_email.split('@')[1].split('.')[0].title() if '@' in recipient_email else "your company"
            
            replacements = {
                'recipient_name': recipient_name_display,
                'company_name': company_name,
                'product_name': product_name,
                'sender_name': sender_name,
                'post_summary': post_summary or 'I would love to explore potential collaboration opportunities.'
            }
            
            # Replace in subject
            for key, value in replacements.items():
                subject = subject.replace(f'{{{{{key}}}}}', str(value))
            
            # Replace in body
            for key, value in replacements.items():
                body = body.replace(f'{{{{{key}}}}}', str(value))
        
        # Use subject hint if provided and Claude didn't override
        if subject_hint and subject == template.subject:
            subject = subject_hint
        
        # Create email record (post_id is nullable for manual emails)
        email = Email(
            tenant_id=tenant_id,
            post_id=None,  # Manual emails don't have a post
            profile_id=None,  # Manual emails may not have a profile
            template_id=template.template_id,
            subject=subject,
            body=body,
            recipients=recipient_email,
            status='draft',
            signal_id=None  # Manual emails don't have signals
        )
        
        db.session.add(email)
        db.session.commit()
        
        logger.info("Manual email generated successfully", extra={
            "email_id": email.email_id,
            "recipient_email": recipient_email,
            "tenant_id": tenant_id
        })
        
        return email
        
    except Exception as e:
        logger.exception("Failed to generate manual email", extra={
            "recipient_email": recipient_email,
            "tenant_id": tenant_id,
            "error": str(e)
        })
        db.session.rollback()
        raise
