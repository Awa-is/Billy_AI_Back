"""
AI Email Generation Endpoints

These endpoints generate emails in memory only (not saved to database).
Frontend stores the response and can either:
- Save as draft via POST /api/emails/drafts
- Send immediately via POST /api/emails/send
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, ValidationError, validates_schema
from app.extensions import db
from app.models.profile import Profile
from app.models.signal import Signal
from app.models.user import User
from app.services.signal_email_generation import build_signal_email_prompt, get_default_template, get_ai_instructions
from app.services.manual_email_generation import build_manual_email_prompt, generate_manual_email
from app.services.email_generation import call_claude_api, extract_first_name
from app.models.email_template import EmailTemplate
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('ai', __name__)


class GenerateDraftSchema(Schema):
    """Schema for single email draft generation."""
    contactId = fields.Str(required=True, error_messages={"required": "contactId is required"})
    signalId = fields.Str(required=True, error_messages={"required": "signalId is required"})  # Required for signal-based emails
    userInstructions = fields.List(fields.Str(), required=False, allow_none=True)  # User's AI preferences


class GenerateAllDraftsSchema(Schema):
    """Schema for generating all drafts for one contact (all signal types)."""
    contactId = fields.Str(required=True, error_messages={"required": "contactId is required"})
    userInstructions = fields.List(fields.Str(), required=False, allow_none=True)  # User's AI preferences


class RefineEmailSchema(Schema):
    """Schema for refining email in real-time."""
    contactId = fields.Str(required=True, error_messages={"required": "contactId is required"})
    signalId = fields.Str(required=True, error_messages={"required": "signalId is required"})
    currentSubject = fields.Str(required=True, error_messages={"required": "currentSubject is required"})
    currentBody = fields.Str(required=True, error_messages={"required": "currentBody is required"})
    refinement = fields.Str(
        required=True,
        validate=lambda x: x in ["tone", "length", "grammar"],
        error_messages={"validator_failed": "refinement must be one of: tone, length, grammar"}
    )
    refinementValue = fields.Str(required=False, allow_none=True)
    userInstructions = fields.List(fields.Str(), required=False, allow_none=True)
    
    @validates_schema
    def validate_refinement_value(self, data, **kwargs):
        """Validate refinementValue based on refinement type."""
        refinement = data.get('refinement')
        refinement_value = data.get('refinementValue')
        
        if refinement == 'tone':
            if not refinement_value:
                raise ValidationError("refinementValue is required when refinement is 'tone'")
            valid_tones = ["Formal", "Informal", "Friendly", "Professional", "Conversational", "Persuasive", "Educational"]
            if refinement_value not in valid_tones:
                raise ValidationError(f"refinementValue for tone must be one of: {', '.join(valid_tones)}")
        elif refinement == 'length':
            if not refinement_value:
                raise ValidationError("refinementValue is required when refinement is 'length'")
            if refinement_value not in ["shorter", "longer"]:
                raise ValidationError("refinementValue for length must be 'shorter' or 'longer'")
        elif refinement == 'grammar':
            # Grammar doesn't need a value
            pass


class GenerateGenericEmailSchema(Schema):
    """Schema for generating generic email for unknown contact."""
    recipientEmail = fields.Str(required=True, error_messages={"required": "recipientEmail is required"})
    recipientName = fields.Str(required=False, allow_none=True)
    companyName = fields.Str(required=False, allow_none=True)
    subject = fields.Str(required=False, allow_none=True)  # Optional subject hint
    userInstructions = fields.List(fields.Str(), required=False, allow_none=True)


generate_draft_schema = GenerateDraftSchema()
generate_all_drafts_schema = GenerateAllDraftsSchema()
refine_email_schema = RefineEmailSchema()
generate_generic_schema = GenerateGenericEmailSchema()


# Signal type to API spec mapping
SIGNAL_TYPE_TO_API_TYPE = {
    'company_news': 'news',
    'career_move': 'career',
    'linkedin_activity': 'thought_leadership',
    'product_launch': 'strategic',
}

# Signal type to label mapping
SIGNAL_TYPE_TO_LABEL = {
    'company_news': 'Company News',
    'career_move': 'Career Change',
    'linkedin_activity': 'Thought Leadership',
    'product_launch': 'Strategic Priority',
}


def _generate_single_draft_in_memory(
    profile: Profile,
    signal: Optional[Signal],
    tenant_id: str,
    sender_name: str,
    user_instructions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate a single email draft in memory (not saved to database).
    
    Returns email data that frontend can store in React state.
    """
    try:
        # Get template
        template = get_default_template(tenant_id)
        if not template:
            raise ValueError(f"No email template found for tenant {tenant_id}")
        
        # Get AI instructions
        ai_instructions = get_ai_instructions(tenant_id)
        
        if signal and signal.post:
            # Signal-based email generation
            # Merge user instructions with AI instructions
            combined_instructions = ai_instructions or ""
            if user_instructions:
                user_instructions_text = "\n".join([f"- {inst}" for inst in user_instructions])
                if combined_instructions:
                    combined_instructions = f"{combined_instructions}\n\nUser-Specific Instructions:\n{user_instructions_text}"
                else:
                    combined_instructions = f"User-Specific Instructions:\n{user_instructions_text}"
            
            prompt = build_signal_email_prompt(
                signal=signal,
                profile=profile,
                template=template,
                sender_name=sender_name,
                ai_instructions=combined_instructions if combined_instructions else None
            )
        else:
            # Manual email generation (no signal)
            recipient_name = profile.person_name or extract_first_name(profile.person_name) if profile.person_name else None
            prompt = build_manual_email_prompt(
                recipient_email=profile.email or "",
                recipient_name=recipient_name,
                template=template,
                sender_name=sender_name,
                subject_hint=None,
                ai_instructions=ai_instructions
            )
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract values
        subject = claude_response.get('subject', template.subject)
        body = claude_response.get('body', template.body)
        
        # Generate preview line (first line or first 100 chars)
        preview_line = None
        if body:
            # Try to get first sentence or first 100 characters
            first_line = body.split('\n')[0].strip()
            if first_line:
                preview_line = first_line[:100] + "..." if len(first_line) > 100 else first_line
            else:
                preview_line = body[:100] + "..." if len(body) > 100 else body
        
        # Map signal type to API format
        signal_type_api = None
        signal_label = None
        if signal:
            signal_type_api = SIGNAL_TYPE_TO_API_TYPE.get(signal.signal_type, 'strategic')
            signal_label = SIGNAL_TYPE_TO_LABEL.get(signal.signal_type, 'Strategic Priority')
        
        # Build response matching API spec format
        email_data = {
            "type": signal_type_api,
            "label": signal_label,
            "subject": subject,
            "body": body,
            "previewLine": preview_line,
            # Additional fields for backward compatibility
            "to": profile.email or "",
            "contactId": profile.profile_id,
            "profile_id": profile.profile_id,
            "signalId": signal.signal_id if signal else None,
            "signal_id": signal.signal_id if signal else None,
            "post_id": signal.post_id if signal and signal.post else None,
            "template_id": template.template_id if template else None
        }
        
        return email_data
        
    except Exception as e:
        logger.exception(f"Failed to generate draft for profile {profile.profile_id}: {e}")
        raise


@bp.route('/generate-draft', methods=['POST'])
@jwt_required()
def generate_draft():
    """
    Generate a single email draft in real-time when user clicks on a signal.
    Frontend sends only IDs - backend fetches profile + posts internally.
    
    Used In UI: SignalDraftPicker.tsx → ComposeView.tsx
    When Called: When user clicks on a contact card in Signal Draft Picker
    UI Elements: Shimmer loading animation while generating, then opens compose view with generated subject/body prefilled
    
    Request Body:
    {
        "contactId": "profile-uuid",
        "signalId": "signal-uuid",
        "userInstructions": ["Keep emails under 100 words", "End with a soft call-to-action"]  // Optional
    }
    
    Response (200 OK):
    {
        "type": "news",
        "label": "Company News",
        "subject": "Re: ACME Corp's AI platform launch - Quick thought",
        "body": "Dear John,\n\nCongratulations on the AI platform launch...",
        "previewLine": "Saw your AI platform launch post - congrats on the milestone..."
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    user_id = get_jwt_identity()
    
    if not tenant_id or not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get user for sender name
    user = User.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    sender_name = "Team"
    if user:
        sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "Team"
    
    # Validate request
    data = request.get_json() or {}
    try:
        validated = generate_draft_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    contact_id = validated['contactId']
    signal_id = validated['signalId']  # Now required
    user_instructions = validated.get('userInstructions')  # Optional list of strings
    
    # Get profile
    profile = Profile.query.filter_by(
        profile_id=contact_id,
        tenant_id=tenant_id
    ).first()
    
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get signal (required)
    signal = Signal.query.filter_by(
        signal_id=signal_id,
        tenant_id=tenant_id
    ).first()
    
    if not signal:
        return jsonify({"error": "Signal not found"}), 404
    
    # Signal detected
    if not signal:
        return jsonify({"error": "Signal not found"}), 404
    
    # Validate signal has post (required for signal-based emails)
    if not signal.post:
        return jsonify({
            "error": "Signal has no associated post"
        }), 400

    
    try:
        # Generate email in memory
        email_data = _generate_single_draft_in_memory(
            profile=profile,
            signal=signal,
            tenant_id=tenant_id,
            sender_name=sender_name,
            user_instructions=user_instructions
        )
        
        # Save email to database automatically
        from app.models.email import Email
        from app.extensions import db
        
        email = Email(
            tenant_id=tenant_id,
            profile_id=profile.profile_id,
            signal_id=signal.signal_id,
            post_id=signal.post_id if signal.post else None,
            template_id=email_data.get('template_id'),
            subject=email_data.get('subject', ''),
            body=email_data.get('body', ''),
            recipients=profile.email or email_data.get('to', ''),
            status='draft',
            approval_status='pending'
        )
        
        db.session.add(email)
        db.session.commit()
        
        # Add email_id to response
        email_data['email_id'] = email.email_id
        email_data['id'] = email.email_id  # For backward compatibility
        
        # Return response matching spec format (not wrapped in "email" key)
        return jsonify(email_data), 200
        
    except Exception as e:
        logger.exception(f"Error generating draft: {e}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to generate email draft",
            "details": str(e)
        }), 500


@bp.route('/generate-all-drafts', methods=['POST'])
@jwt_required()
def generate_all_drafts():
    """
    Generate all available drafts for a contact based on their signals.
    Used in "Review All" flow.
    
    Used In UI: BatchOutreachMode.tsx - "Review All" batch mode
    When Called: When user clicks "Review All (N)" button in Signal Draft Picker,
                 called for EACH contact in the batch (can be parallel)
    UI Elements: Progress indicator showing "Generating 1 of 10...", then displays
                 all drafts in carousel view with approve/skip/edit options
    
    Request Body:
    {
        "contactId": "profile-uuid",
        "userInstructions": ["Keep emails under 100 words", "End with a soft call-to-action"]  // Optional
    }
    
    Response (200 OK):
    {
        "contact": {
            "id": "profile-uuid",
            "firstName": "John",
            "lastName": "Smith",
            "email": "john.smith@acmecorp.com"
        },
        "drafts": [
            {
                "signalId": "signal-uuid-1",
                "type": "news",
                "label": "Company News",
                "subject": "Re: ACME Corp's AI platform launch - Quick thought",
                "body": "Dear John,\n\nCongratulations on the AI platform launch...",
                "previewLine": "Saw your AI platform launch post..."
            },
            {
                "signalId": "signal-uuid-2",
                "type": "thought_leadership",
                "label": "Thought Leadership",
                "subject": "Your take on AI augmenting human capabilities",
                "body": "Dear John,\n\nYour recent post about AI augmenting...",
                "previewLine": "Really resonated with your AI adoption perspective..."
            }
        ]
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    user_id = get_jwt_identity()
    
    if not tenant_id or not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get user for sender name
    user = User.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    sender_name = "Team"
    if user:
        sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "Team"
    
    # Validate request
    data = request.get_json() or {}
    try:
        validated = generate_all_drafts_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    contact_id = validated['contactId']
    user_instructions = validated.get('userInstructions')  # Optional list of strings
    
    # Get profile
    profile = Profile.query.filter_by(
        profile_id=contact_id,
        tenant_id=tenant_id
    ).first()
    
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get ALL signals for this contact (only those with posts)
    signals = Signal.query.filter_by(
        profile_id=contact_id,
        tenant_id=tenant_id
    ).filter(Signal.post_id.isnot(None)).order_by(Signal.created_at.desc()).all()
    
    # Build contact object matching spec format
    # Extract first/last name from person_name
    first_name = profile.first_name
    last_name = profile.last_name
    
    if not first_name or not last_name:
        if profile.person_name:
            name_parts = profile.person_name.split()
            if len(name_parts) >= 2:
                first_name = first_name or name_parts[0]
                last_name = last_name or ' '.join(name_parts[1:])
            elif len(name_parts) == 1:
                first_name = first_name or name_parts[0]
                last_name = last_name or ""
    
    contact_obj = {
        "id": profile.profile_id,
        "firstName": first_name,
        "lastName": last_name,
        "email": profile.email or ""
    }
    
    if not signals:
        # No signals found - return empty drafts array
        return jsonify({
            "contact": contact_obj,
            "drafts": []
        }), 200
    
    # Generate one draft per signal (in memory only)
    drafts = []
    
    for signal in signals:
        try:
            # Validate signal has post (required for email generation)
            if not signal.post:
                logger.warning(f"Signal {signal.signal_id} has no associated post, skipping")
                continue

            
            # Generate draft for this signal
            email_data = _generate_single_draft_in_memory(
                profile=profile,
                signal=signal,
                tenant_id=tenant_id,
                sender_name=sender_name,
                user_instructions=user_instructions
            )
            
            # Format draft to match spec (only include required fields)
            draft_obj = {
                "signalId": signal.signal_id,
                "type": email_data.get('type'),
                "label": email_data.get('label'),
                "subject": email_data.get('subject'),
                "body": email_data.get('body'),
                "previewLine": email_data.get('previewLine')
            }
            
            drafts.append(draft_obj)
            
        except Exception as e:
            logger.exception(f"Failed to generate draft for signal {signal.signal_id} of profile {profile.profile_id}: {e}")
            # Continue with other signals even if one fails
    
    return jsonify({
        "contact": contact_obj,
        "drafts": drafts
    }), 200


def _refine_email_in_memory(
    profile: Profile,
    signal: Signal,
    current_subject: str,
    current_body: str,
    refinement: str,
    refinement_value: Optional[str],
    tenant_id: str,
    sender_name: str,
    user_instructions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Refine an email in memory (not saved to database).
    
    Args:
        profile: Profile object
        signal: Signal object
        current_subject: Current email subject
        current_body: Current email body
        refinement: Type of refinement (tone, length, grammar)
        refinement_value: Value for refinement (e.g., "Formal" for tone, "shorter" for length)
        tenant_id: Tenant ID
        sender_name: Sender name
        user_instructions: Optional user instructions
        
    Returns:
        Dict with refined subject and body
    """
    try:
        # Get template
        template = get_default_template(tenant_id)
        if not template:
            raise ValueError(f"No email template found for tenant {tenant_id}")
        
        # Get AI instructions
        ai_instructions = get_ai_instructions(tenant_id)
        
        # Merge user instructions with AI instructions
        combined_instructions = ai_instructions or ""
        if user_instructions:
            user_instructions_text = "\n".join([f"- {inst}" for inst in user_instructions])
            if combined_instructions:
                combined_instructions = f"{combined_instructions}\n\nUser-Specific Instructions:\n{user_instructions_text}"
            else:
                combined_instructions = f"User-Specific Instructions:\n{user_instructions_text}"
        
        # Convert refinement format to internal format
        refinement_options = {}
        if refinement == "tone" and refinement_value:
            refinement_options["tone"] = refinement_value
        elif refinement == "length" and refinement_value:
            if refinement_value == "shorter":
                refinement_options["make_shorter"] = True
            elif refinement_value == "longer":
                refinement_options["make_longer"] = True
        elif refinement == "grammar":
            refinement_options["fix_spelling_grammar"] = True
        
        # Get post and company info
        post = signal.post if signal else None
        if not post:
            raise ValueError("Signal has no associated post")
        
        company_name = post.company.name if post.company else "the company"
        post_text = post.post_text or ""
        recipient_name = extract_first_name(profile.person_name)
        headline = profile.headline or ""
        
        # Build signal context
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
        if combined_instructions:
            instructions_section = f"""
Additional Instructions:
{combined_instructions}
"""
        
        # Build refinement criteria section
        refinement_criteria = []
        
        if refinement_options.get('tone'):
            tone = refinement_options['tone']
            refinement_criteria.append(f"- **Tone**: Write in a {tone.lower()} tone")
        
        if refinement_options.get('make_shorter'):
            refinement_criteria.append("- **Length**: Make the email significantly shorter and more concise")
        elif refinement_options.get('make_longer'):
            refinement_criteria.append("- **Length**: Expand the email to provide more detail and context")
        
        if refinement_options.get('fix_spelling_grammar'):
            refinement_criteria.append("- **Grammar & Spelling**: Fix all spelling errors, grammatical mistakes, and improve sentence structure")
        
        criteria_section = ""
        if refinement_criteria:
            criteria_section = f"""
Specific Refinement Requirements:
{chr(10).join(refinement_criteria)}
"""
        
        # Build refine prompt
        prompt = f"""You are an AI assistant helping to refine and improve personalized outreach emails for B2B sales.

Current Email to Refine:
Subject: {current_subject}
Body: {current_body}

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
Your task:
1. Review the current email subject and body
2. Improve the email to make it:
   - More engaging and compelling
   - Better personalized to the recipient
   - More professional yet friendly
   - Better aligned with the signal context (if provided)
   - More natural and conversational
3. Maintain the same general structure and intent
4. Ensure all template placeholders are properly filled:
   - {{recipient_name}} → Use first name only: {recipient_name}
   - {{company_name}} → {company_name}
   - {{sender_name}} → {sender_name}
   - {{post_summary}} → Generate 2-3 sentences about the signal

Output format (JSON):
{{
  "subject": "improved subject line",
  "body": "improved email body"
}}

Guidelines for refinement:
- Keep it professional but friendly
- Make it more personalized when possible
- Improve clarity and impact
- Ensure it's natural and conversational
- Reference the signal context naturally (if provided)
- Maintain appropriate length (not too long, not too short)

Refine the email now:"""
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract refined content
        refined_subject = claude_response.get('subject', current_subject)
        refined_body = claude_response.get('body', current_body)
        
        # Build refinement applied string
        refinement_applied = f"{refinement}"
        if refinement_value:
            refinement_applied += f": {refinement_value}"
        
        return {
            "subject": refined_subject,
            "body": refined_body,
            "refinementApplied": refinement_applied
        }
        
    except Exception as e:
        logger.exception(f"Failed to refine email in memory: {e}")
        raise


@bp.route('/refine', methods=['POST'])
@jwt_required()
def refine_email():
    """
    Refines an existing email (change tone, make shorter/longer, fix grammar).
    Backend needs contactId + signalId to fetch profile + posts for context.
    
    Used In UI: RefineMenu.tsx - Dropdown menu in compose view
    When Called: When user clicks "Refine" button and selects an option
    UI Elements: Wand icon button → dropdown with tone options, Make Shorter, Make Longer, Fix Spelling & Grammar
    
    Request Body:
    {
        "contactId": "profile-uuid",
        "signalId": "signal-uuid",
        "currentSubject": "Re: ACME Corp's AI platform launch",
        "currentBody": "Dear John,\n\nCongratulations on the launch...",
        "refinement": "tone",
        "refinementValue": "Formal",
        "userInstructions": ["Keep emails under 100 words"]
    }
    
    Response (200 OK):
    {
        "subject": "Re: ACME Corp's AI platform launch",
        "body": "Dear Mr. Smith,\n\nI would like to extend...",
        "refinementApplied": "tone: Formal"
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    user_id = get_jwt_identity()
    
    if not tenant_id or not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get user for sender name
    user = User.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    sender_name = "Team"
    if user:
        sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "Team"
    
    # Validate request
    data = request.get_json() or {}
    try:
        validated = refine_email_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    contact_id = validated['contactId']
    signal_id = validated['signalId']
    current_subject = validated['currentSubject']
    current_body = validated['currentBody']
    refinement = validated['refinement']
    refinement_value = validated.get('refinementValue')
    user_instructions = validated.get('userInstructions')
    
    # Get profile
    profile = Profile.query.filter_by(
        profile_id=contact_id,
        tenant_id=tenant_id
    ).first()
    
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    
    # Get signal
    signal = Signal.query.filter_by(
        signal_id=signal_id,
        tenant_id=tenant_id
    ).first()
    
    if not signal:
        return jsonify({"error": "Signal not found"}), 404
    
    # Validate signal has post (required for refinement context)
    if not signal.post:
        return jsonify({
            "error": "Signal has no associated post"
        }), 400
    
    try:
        # Refine email in memory
        refined_data = _refine_email_in_memory(
            profile=profile,
            signal=signal,
            current_subject=current_subject,
            current_body=current_body,
            refinement=refinement,
            refinement_value=refinement_value,
            tenant_id=tenant_id,
            sender_name=sender_name,
            user_instructions=user_instructions
        )
        
        return jsonify(refined_data), 200
        
    except Exception as e:
        logger.exception(f"Error refining email: {e}")
        return jsonify({
            "error": "Failed to refine email",
            "details": str(e)
        }), 500


def _generate_generic_email_in_memory(
    recipient_email: str,
    recipient_name: Optional[str],
    company_name: Optional[str],
    subject_hint: Optional[str],
    tenant_id: str,
    sender_name: str,
    user_instructions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate a generic email in memory for unknown contact (not saved to database).
    
    Args:
        recipient_email: Recipient email address
        recipient_name: Recipient name (optional)
        company_name: Company name (optional)
        subject_hint: Optional subject hint
        tenant_id: Tenant ID
        sender_name: Sender name
        user_instructions: Optional user instructions
        
    Returns:
        Dict with subject and body
    """
    try:
        # Get template
        template = get_default_template(tenant_id)
        if not template:
            raise ValueError(f"No email template found for tenant {tenant_id}")
        
        # Get AI instructions
        ai_instructions = get_ai_instructions(tenant_id)
        
        # Merge user instructions with AI instructions
        combined_instructions = ai_instructions or ""
        if user_instructions:
            user_instructions_text = "\n".join([f"- {inst}" for inst in user_instructions])
            if combined_instructions:
                combined_instructions = f"{combined_instructions}\n\nUser-Specific Instructions:\n{user_instructions_text}"
            else:
                combined_instructions = f"User-Specific Instructions:\n{user_instructions_text}"
        
        # Build prompt using manual email generation service
        prompt = build_manual_email_prompt(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            template=template,
            sender_name=sender_name,
            subject_hint=subject_hint,
            ai_instructions=combined_instructions if combined_instructions else None
        )
        
        # Call Claude API
        claude_response = call_claude_api(prompt)
        
        # Extract values
        subject = claude_response.get('subject', template.subject)
        body = claude_response.get('body', template.body)
        
        # If subject hint was provided and Claude didn't use it, use it as fallback
        if subject_hint and subject == template.subject:
            subject = subject_hint
        
        # Fallback: if Claude didn't provide subject/body, do manual replacement
        if subject == template.subject or body == template.body:
            recipient_name_display = recipient_name or extract_first_name(recipient_email.split('@')[0])
            company_display = company_name or recipient_email.split('@')[1].split('.')[0] if '@' in recipient_email else "your company"
            
            replacements = {
                'recipient_name': recipient_name_display,
                'company_name': company_display,
                'product_name': 'our solution',
                'sender_name': sender_name,
                'post_summary': 'I\'d love to discuss how we might work together to address challenges in your industry.'
            }
            
            # Replace in subject
            for key, value in replacements.items():
                subject = subject.replace(f'{{{{{key}}}}}', str(value))
            
            # Replace in body
            for key, value in replacements.items():
                body = body.replace(f'{{{{{key}}}}}', str(value))
        
        return {
            "subject": subject,
            "body": body
        }
        
    except Exception as e:
        logger.exception(f"Failed to generate generic email: {e}")
        raise


@bp.route('/generate-generic', methods=['POST'])
@jwt_required()
def generate_generic():
    """
    Generates email for contacts NOT in database. Used when user composes to unknown email address.
    
    Used In UI: ComposeView.tsx - "Compose Directly" flow
    When Called: When user clicks "Compose Directly" and enters an email that doesn't exist in the system, then requests AI generation
    UI Elements: Compose form with manual email entry, "Generate" button, generates basic email without signal-based personalization
    
    Request Body:
    {
        "recipientEmail": "unknown@company.com",
        "recipientName": "John",
        "companyName": "ACME Corp",
        "subject": "Quick Introduction",
        "userInstructions": ["Keep emails under 100 words"]
    }
    
    Response (200 OK):
    {
        "subject": "Quick Introduction",
        "body": "Dear John,\n\nI'm reaching out to connect with you at ACME Corp.\n\nI'd love to discuss how we might work together to address challenges in your industry.\n\nWould you have 15 minutes for a quick call this week?\n\nBest regards"
    }
    
    When to use:
    - Contact not in database (no signals)
    - User typing email address manually in "Compose Directly"
    - No LinkedIn profile/posts available
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    user_id = get_jwt_identity()
    
    if not tenant_id or not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get user for sender name
    user = User.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
    sender_name = "Team"
    if user:
        sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email or "Team"
    
    # Validate request
    data = request.get_json() or {}
    try:
        validated = generate_generic_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    recipient_email = validated['recipientEmail']
    recipient_name = validated.get('recipientName')
    company_name = validated.get('companyName')
    subject_hint = validated.get('subject')
    user_instructions = validated.get('userInstructions')
    
    try:
        # Generate email in memory
        email_data = _generate_generic_email_in_memory(
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            company_name=company_name,
            subject_hint=subject_hint,
            tenant_id=tenant_id,
            sender_name=sender_name,
            user_instructions=user_instructions
        )
        
        return jsonify(email_data), 200
        
    except Exception as e:
        logger.exception(f"Error generating generic email: {e}")
        return jsonify({
            "error": "Failed to generate email",
            "details": str(e)
        }), 500
