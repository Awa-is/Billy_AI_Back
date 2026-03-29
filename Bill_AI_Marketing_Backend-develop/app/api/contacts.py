"""
Contacts API Endpoint

GET /api/contacts/with-signals - List contacts with signals for Signal Draft Picker
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from app.extensions import db
from app.models.profile import Profile
from app.models.signal import Signal
from app.models.post import Post
from app.models.company import Company
from app.models.email import Email
from sqlalchemy import or_, func, distinct
from sqlalchemy.orm import joinedload
from datetime import datetime
import math
import json
import urllib.parse

bp = Blueprint('contacts', __name__)


# Signal type mapping from internal to API spec format
SIGNAL_TYPE_TO_SPEC = {
    'company_news': 'companyNews',
    'career_move': 'careerChange',
    'linkedin_activity': 'linkedinActivity',
    'product_launch': 'strategicPriority',  # Product launches are strategic priorities
}

# Reverse mapping for available draft types
# Maps internal signal types to draft types (used in API responses)
SIGNAL_TYPE_TO_DRAFT_TYPE = {
    'company_news': 'news',              # companyNews → news
    'career_move': 'career',             # careerChange → career
    'linkedin_activity': 'thought_leadership',  # linkedinActivity → thought_leadership
    'product_launch': 'strategic',       # strategicPriority → strategic (product launches are strategic)
}


def build_signal_summary(signal, email=None, spec_format=True):
    """Build signal summary in API spec format."""
    signal_type_internal = signal.signal_type
    signal_type_spec = SIGNAL_TYPE_TO_SPEC.get(signal_type_internal, 'strategicPriority')
    
    summary = {}
    
    if signal_type_spec == 'companyNews':
        # Company news/announcements
        # Format: {headline, date, type: "launch" | "funding" | "expansion" | "partnership"}
        post = signal.post
        if post:
            headline = post.post_text[:100] + "..." if post.post_text and len(post.post_text) > 100 else (post.post_text or "Company update")
            date = post.post_date.isoformat() if post.post_date else signal.created_at.isoformat()
            
            # Determine type from keywords or signal metadata
            signal_type_value = "announcement"  # default
            if signal_type_internal == 'product_launch':
                signal_type_value = "launch"
            elif signal.signal_metadata:
                # Check metadata for type hints
                metadata = signal.signal_metadata if isinstance(signal.signal_metadata, dict) else {}
                if metadata.get('type') in ["launch", "funding", "expansion", "partnership"]:
                    signal_type_value = metadata.get('type')
                elif 'funding' in (signal.keywords or '').lower():
                    signal_type_value = "funding"
                elif 'expansion' in (signal.keywords or '').lower():
                    signal_type_value = "expansion"
                elif 'partnership' in (signal.keywords or '').lower():
                    signal_type_value = "partnership"
            elif signal.keywords:
                # Infer from keywords
                keywords_lower = signal.keywords.lower()
                if 'funding' in keywords_lower:
                    signal_type_value = "funding"
                elif 'expansion' in keywords_lower:
                    signal_type_value = "expansion"
                elif 'partnership' in keywords_lower:
                    signal_type_value = "partnership"
            
            summary = {
                "id": signal.signal_id,
                "postId": signal.post_id,
                "headline": headline,
                "date": date,
                "type": signal_type_value
            }
        else:
            summary = {
                "id": signal.signal_id,
                "postId": signal.post_id,
                "headline": signal.keywords or "Company update",
                "date": signal.created_at.isoformat(),
                "type": "announcement"
            }
    
    elif signal_type_spec == 'careerChange':
        # Career/role change
        # Format: {previousRole, newRole, date}
        profile = signal.profile
        
        # Try to extract previous and new roles from profile experiences
        previous_role = None
        new_role = None
        
        if profile:
            # Get current role from job_title
            new_role = profile.job_title
            
            # Try to extract previous role from experiences JSON
            if profile.experiences:
                try:
                    experiences = json.loads(profile.experiences) if isinstance(profile.experiences, str) else profile.experiences
                    if isinstance(experiences, list) and len(experiences) > 1:
                        # Second most recent experience is previous role
                        previous_role = experiences[1].get('title') if isinstance(experiences[1], dict) else None
                except (json.JSONDecodeError, TypeError, IndexError):
                    pass
        
        # Fallback to signal metadata if available
        if signal.signal_metadata:
            metadata = signal.signal_metadata if isinstance(signal.signal_metadata, dict) else {}
            if not previous_role:
                previous_role = metadata.get('previousRole') or metadata.get('previous_role')
            if not new_role:
                new_role = metadata.get('newRole') or metadata.get('new_role')
        
        summary = {
            "id": signal.signal_id,
            "postId": signal.post_id,
            "previousRole": previous_role or "Previous role",
            "newRole": new_role or "Current role",
            "date": signal.created_at.isoformat()
        }
    
    elif signal_type_spec == 'linkedinActivity':
        # LinkedIn activity
        post = signal.post
        if post:
            # Extract topic from post text (first 50 chars)
            topic = post.post_text[:50] + "..." if post.post_text and len(post.post_text) > 50 else (post.post_text or "Recent activity")
            summary = {
                "id": signal.signal_id,
                "postId": signal.post_id,
                "recentPostTopic": topic.lower(),
                "postDate": post.post_date.isoformat() if post.post_date else signal.created_at.isoformat(),
                "engagement": "high" if signal.score > 70 else "medium" if signal.score > 50 else "low"
            }
        else:
            summary = {
                "id": signal.signal_id,
                "postId": signal.post_id,
                "recentPostTopic": "LinkedIn activity",
                "postDate": signal.created_at.isoformat(),
                "engagement": "medium"
            }
    
    elif signal_type_spec == 'strategicPriority':
        # Strategic priorities
        # Format: {source: "earnings_call" | "press_release" | "annual_report", focus, quarter}
        post = signal.post
        
        # Extract source from metadata or infer from signal
        source = "press_release"  # default
        if signal.signal_metadata:
            metadata = signal.signal_metadata if isinstance(signal.signal_metadata, dict) else {}
            source_value = metadata.get('source')
            if source_value in ["earnings_call", "press_release", "annual_report"]:
                source = source_value
        
        # Extract focus from post text or keywords
        focus = None
        if post and post.post_text:
            # Use first 100 chars of post as focus
            focus = post.post_text[:100] + "..." if len(post.post_text) > 100 else post.post_text
        elif signal.keywords:
            focus = signal.keywords
        else:
            focus = "Strategic priorities"
        
        # Extract quarter from metadata or infer from date
        quarter = None
        if signal.signal_metadata:
            metadata = signal.signal_metadata if isinstance(signal.signal_metadata, dict) else {}
            quarter = metadata.get('quarter')
        
        if not quarter and signal.created_at:
            # Infer quarter from date
            month = signal.created_at.month
            year = signal.created_at.year
            if month <= 3:
                quarter = f"Q1 {year}"
            elif month <= 6:
                quarter = f"Q2 {year}"
            elif month <= 9:
                quarter = f"Q3 {year}"
            else:
                quarter = f"Q4 {year}"
        
        summary = {
            "id": signal.signal_id,
            "postId": signal.post_id,
            "source": source,
            "focus": focus,
            "quarter": quarter or "Current quarter"
        }
    
    # Add email ID and content if available
    if email:
        summary["emailId"] = email.email_id
        summary["emailContent"] = {
            "id": email.email_id,
            "subject": email.subject,
            "body": email.body,
            "status": email.status
        }
    
    return summary


@bp.route('/filters', methods=['GET'])
@jwt_required()
def get_contact_filters():
    """
    Get available filters for contacts (verticals/industries and functions).
    
    Returns lists of unique industries and job functions found in the profiles.
    Used to populate dropdowns in SignalDraftPicker.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    # Get distinct verticals (industries) from profiles with signals
    # We only care about verticals that have signals
    verticals_query = db.session.query(
        distinct(Profile.company_industry)
    ).join(
        Email, Profile.profile_id == Email.profile_id
    ).join(
        Signal, Email.signal_id == Signal.signal_id
    ).filter(
        Profile.tenant_id == tenant_id,
        Signal.tenant_id == tenant_id,
        Profile.company_industry.isnot(None), 
        Profile.company_industry != ''
    )
    
    verticals = set()
    for row in verticals_query.all():
        verticals.add(row[0])
        
    # Also check 'industry' field
    verticals_query_2 = db.session.query(
        distinct(Profile.industry)
    ).join(
        Email, Profile.profile_id == Email.profile_id
    ).join(
        Signal, Email.signal_id == Signal.signal_id
    ).filter(
        Profile.tenant_id == tenant_id,
        Signal.tenant_id == tenant_id,
        Profile.industry.isnot(None),
        Profile.industry != ''
    )
    
    for row in verticals_query_2.all():
        verticals.add(row[0])

    # Standard functions (Departments)
    # Hardcoded as per design, since extracting them from job titles reliably requires NLP
    functions = [
        "Marketing", "Sales", "Operations", "Engineering", 
        "Finance", "HR", "Product", "Legal", "Executive"
    ]
    
    return jsonify({
        "verticals": sorted(list(verticals)),
        "functions": sorted(functions)
    }), 200


@bp.route('/with-signals', methods=['GET'])
@jwt_required()
def list_contacts_with_signals():
    """
    Retrieves contacts that have signals available for AI-generated drafts.
    Used in Signal Draft Picker.
    
    Used In UI: SignalDraftPicker.tsx - Modal showing contacts with signals
    When Called: When user clicks "New Outreach" button, this modal opens and loads contacts
    UI Elements: Contact list with avatars, signal badges (Company News, Career Move, etc.), 
                 vertical/function filters, search box, "Review All" button for batch mode
    
    Query Parameters:
        - vertical: Filter by vertical (e.g., "Beauty", "SaaS / Technology")
        - function: Filter by function (e.g., "Marketing", "Sales")
        - search: Search by name, company, or email
        - page: Page number (default: 1)
        - limit: Items per page (default: 20)
    
    Response (200 OK):
    {
        "data": [
            {
                "id": 1,
                "firstName": "John",
                "lastName": "Smith",
                "email": "john.smith@acmecorp.com",
                "vertical": "Enterprise Software",
                "function": "Operations",
                "seniority": "VP of Operations",
                "company": {
                    "id": "1",
                    "name": "ACME Corp"
                },
                "signals": {
                    "companyNews": {
                        "headline": "ACME Corp Launches New AI Platform",
                        "date": "2025-12-10",
                        "type": "launch"
                    },
                    "linkedinActivity": {
                        "recentPostTopic": "the future of enterprise AI adoption",
                        "postDate": "2025-12-14",
                        "engagement": "high"
                    }
                },
                "signalCount": 2,
                "availableDraftTypes": ["news", "thought_leadership"]
            }
        ],
        "pagination": {
            "page": 1,
            "limit": 20,
            "total": 15,
            "totalPages": 1
        }
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get query parameters
    # Flask automatically decodes URL-encoded parameters, but we'll be explicit
    import urllib.parse
    vertical_raw = request.args.get('vertical', '')
    vertical = urllib.parse.unquote(vertical_raw).strip() if vertical_raw else ''
    
    function_raw = request.args.get('function', '')
    function = urllib.parse.unquote(function_raw).strip() if function_raw else ''
    
    search_raw = request.args.get('search', '')
    search = urllib.parse.unquote(search_raw).strip() if search_raw else ''
    
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    
    # Validate pagination
    if page < 1:
        page = 1
    if limit < 1 or limit > 100:
        limit = 20
    
    # Base query: Get profiles that have signals
    # Join with Emails and Signals to get profiles with at least one signal-based draft
    base_query = db.session.query(Profile).join(
        Email, Profile.profile_id == Email.profile_id
    ).join(
        Signal, Email.signal_id == Signal.signal_id
    ).filter(
        Profile.tenant_id == tenant_id,
        Signal.tenant_id == tenant_id
    ).distinct()
    
    # Apply filters
    if vertical:
        # Filter by industry or company_industry (case-insensitive partial match)
        # Handle both exact matches and partial matches
        base_query = base_query.filter(
            or_(
                Profile.industry.ilike(f'%{vertical}%'),
                Profile.company_industry.ilike(f'%{vertical}%'),
                Profile.industry.ilike(f'{vertical}%'),
                Profile.company_industry.ilike(f'{vertical}%')
            )
        )
    
    if function:
        # Filter by job_title or extract from experiences
        base_query = base_query.filter(
            or_(
                Profile.job_title.ilike(f'%{function}%'),
                Profile.headline.ilike(f'%{function}%')
            )
        )
    
    if search:
        # Search by name, company, or email
        search_term = f'%{search}%'
        base_query = base_query.filter(
            or_(
                Profile.person_name.ilike(search_term),
                Profile.full_name.ilike(search_term),
                Profile.first_name.ilike(search_term),
                Profile.last_name.ilike(search_term),
                Profile.email.ilike(search_term),
                Profile.company.ilike(search_term),
                Profile.company_name.ilike(search_term)
            )
        )
    
    # Get total count
    total = base_query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    profiles = base_query.offset(offset).limit(limit).all()
    
    # Build response data
    contacts_data = []
    
    for profile in profiles:
        # Get all signals for this profile via generated emails
        signals = db.session.query(Signal).join(
            Email, Signal.signal_id == Email.signal_id
        ).filter(
            Email.profile_id == profile.profile_id,
            Email.tenant_id == tenant_id,
            Signal.tenant_id == tenant_id
        ).options(
            joinedload(Signal.post).joinedload(Post.company)
        ).order_by(Signal.created_at.desc()).all()
        
        if not signals:
            continue  # Skip if no signals (shouldn't happen due to join, but safety check)
        
        # Group signals by type (spec format)
        signals_by_type = {}
        available_draft_types = set()
        
        for signal in signals:
            # Skip signals without posts (as they cannot generate valid emails)
            # if not signal.post:
            #    continue
                
            signal_type_spec = SIGNAL_TYPE_TO_SPEC.get(signal.signal_type, 'strategicPriority')
            draft_type = SIGNAL_TYPE_TO_DRAFT_TYPE.get(signal.signal_type, 'news')
            available_draft_types.add(draft_type)
            
            # Only include the most recent signal of each type
            if signal_type_spec not in signals_by_type:
                # Fetch associated email if exists for THIS profile
                email = Email.query.filter_by(
                    signal_id=signal.signal_id,
                    profile_id=profile.profile_id,
                    tenant_id=tenant_id
                ).order_by(Email.created_at.desc()).first()
                
                signals_by_type[signal_type_spec] = build_signal_summary(signal, email)
        
        # Get company info from signals (signals have company_id)
        company_info = None
        if signals and signals[0].company_id:
            company = Company.query.filter_by(
                company_id=signals[0].company_id,
                tenant_id=tenant_id
            ).first()
            if company:
                company_info = {
                    "id": company.company_id,
                    "name": company.name
                }
        
        # Fallback to profile company fields if no company from signals
        if not company_info and (profile.company or profile.company_name):
            company_info = {
                "id": None,  # No company_id available
                "name": profile.company or profile.company_name
            }
        
        # Extract seniority from job_title or experiences
        seniority = profile.job_title
        if not seniority and profile.experiences:
            try:
                experiences = json.loads(profile.experiences) if isinstance(profile.experiences, str) else profile.experiences
                if experiences and isinstance(experiences, list) and len(experiences) > 0:
                    latest_exp = experiences[0]
                    if isinstance(latest_exp, dict):
                        seniority = latest_exp.get('title') or latest_exp.get('position')
            except:
                pass
        
        # Extract vertical from industry
        vertical_value = profile.company_industry or profile.industry
        
        # Extract function from job_title
        function_value = profile.job_title
        
        contact_data = {
            "id": profile.profile_id,
            "firstName": profile.first_name or (profile.person_name.split()[0] if profile.person_name and ' ' in profile.person_name else None),
            "lastName": profile.last_name or (profile.person_name.split()[-1] if profile.person_name and ' ' in profile.person_name else None),
            "email": profile.email,
            "vertical": vertical_value,
            "function": function_value,
            "seniority": seniority,
            "company": company_info,
            "signals": signals_by_type,
            "signalCount": len(signals),
            "availableDraftTypes": sorted(list(available_draft_types))
        }
        
        contacts_data.append(contact_data)
    
    # Calculate pagination metadata
    total_pages = math.ceil(total / limit) if total > 0 else 0
    
    return jsonify({
        "data": contacts_data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "totalPages": total_pages
        }
    }), 200


@bp.route('/lookup', methods=['GET'])
@jwt_required()
def lookup_contact():
    """
    Looks up a contact by email address. Used when user types email in compose view.
    
    Used In UI: ComposeView.tsx - "Compose Directly" flow
    When Called: When user types an email address in the "To" field and tabs out or clicks generate
    UI Elements: If contact found → shows contact card with signals and can generate signal-based drafts. 
                 If not found → uses generic AI generation.
    
    Query Parameters:
        - email: Email address to look up (required)
    
    Response (FOUND) 200 OK:
    {
        "found": true,
        "contact": {
            "id": 1,
            "firstName": "John",
            "lastName": "Smith",
            "email": "john.smith@acmecorp.com",
            "vertical": "Enterprise Software",
            "seniority": "VP of Operations",
            "company": {
                "id": "1",
                "name": "ACME Corp"
            },
            "signals": {
                "companyNews": {
                    "headline": "ACME Corp Launches New AI Platform",
                    "date": "2025-12-10",
                    "type": "launch"
                }
            }
        }
    }
    
    Response (NOT FOUND) 200 OK:
    {
        "found": false,
        "contact": null
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get email from query parameters
    email = request.args.get('email', '').strip()
    
    if not email:
        return jsonify({
            "error": "Validation failed",
            "details": {"email": ["email parameter is required"]}
        }), 400
    
    # Look up profile by email
    profile = Profile.query.filter_by(
        email=email,
        tenant_id=tenant_id
    ).first()
    
    if not profile:
        # Contact not found
        return jsonify({
            "found": False,
            "contact": None
        }), 200
    
    # Contact found - get signals
    # Contact found - get signals via Email association
    signals = db.session.query(Signal).join(
        Email, Signal.signal_id == Email.signal_id
    ).filter(
        Email.profile_id == profile.profile_id,
        Email.tenant_id == tenant_id,
        Signal.tenant_id == tenant_id
    ).options(
        joinedload(Signal.post).joinedload(Post.company)
    ).order_by(Signal.created_at.desc()).all()
    
    # Group signals by type (spec format)
    signals_by_type = {}
    
    for signal in signals:
        # Skip signals without posts
        if not signal.post:
            continue
            
        signal_type_spec = SIGNAL_TYPE_TO_SPEC.get(signal.signal_type, 'strategicPriority')
        
        # Only include the most recent signal of each type
        if signal_type_spec not in signals_by_type:
            # Fetch associated email if exists for THIS profile
            email = Email.query.filter_by(
                signal_id=signal.signal_id,
                profile_id=profile.profile_id,
                tenant_id=tenant_id
            ).order_by(Email.created_at.desc()).first()
            
            signals_by_type[signal_type_spec] = build_signal_summary(signal, email)
    
    # Get company info from signals
    company_info = None
    if signals and signals[0].company_id:
        company = Company.query.filter_by(
            company_id=signals[0].company_id,
            tenant_id=tenant_id
        ).first()
        if company:
            company_info = {
                "id": company.company_id,
                "name": company.name
            }
    
    # Fallback to profile company fields
    if not company_info and (profile.company or profile.company_name):
        company_info = {
            "id": None,
            "name": profile.company or profile.company_name
        }
    
    # Extract seniority from job_title or experiences
    seniority = profile.job_title
    if not seniority and profile.experiences:
        try:
            experiences = json.loads(profile.experiences) if isinstance(profile.experiences, str) else profile.experiences
            if experiences and isinstance(experiences, list) and len(experiences) > 0:
                latest_exp = experiences[0]
                if isinstance(latest_exp, dict):
                    seniority = latest_exp.get('title') or latest_exp.get('position')
        except:
            pass
    
    # Extract vertical from industry
    vertical_value = profile.company_industry or profile.industry
    
    # Build contact response
    contact_data = {
        "id": profile.profile_id,
        "firstName": profile.first_name or (profile.person_name.split()[0] if profile.person_name and ' ' in profile.person_name else None),
        "lastName": profile.last_name or (profile.person_name.split()[-1] if profile.person_name and ' ' in profile.person_name else None),
        "email": profile.email,
        "vertical": vertical_value,
        "seniority": seniority,
        "company": company_info,
        "signals": signals_by_type
    }
    
    return jsonify({
        "found": True,
        "contact": contact_data
    }), 200
