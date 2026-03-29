"""
Metadata API Endpoints

Provides metadata for filtering and UI dropdowns (verticals, functions, etc.)
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from app.extensions import db
from app.models.profile import Profile
from sqlalchemy import distinct, func, or_

bp = Blueprint('metadata', __name__)


@bp.route('/verticals', methods=['GET'])
@jwt_required()
def get_verticals():
    """
    Get available verticals for filtering.
    
    Used In UI: SignalDraftPicker.tsx
    When Called: On component mount to populate the vertical filter dropdown
    UI Elements: "All Verticals" dropdown with options like Beauty, SaaS / Technology, Healthcare, etc.
    
    Returns:
        200 OK with list of unique verticals from profiles
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get distinct verticals from profiles
    # Verticals come from company_industry or industry fields
    # Filter by tenant_id and exclude null/empty values
    verticals_set = set()
    
    # Get verticals from company_industry field
    company_industries = db.session.query(
        distinct(Profile.company_industry)
    ).filter(
        Profile.tenant_id == tenant_id,
        Profile.company_industry.isnot(None),
        Profile.company_industry != '',
        Profile.company_industry != 'None'
    ).all()
    
    for row in company_industries:
        vertical = row[0] if isinstance(row, tuple) else row
        vertical_str = str(vertical).strip()
        # Remove tuple formatting if present
        if vertical_str.startswith("('") and vertical_str.endswith("',)"):
            vertical_str = vertical_str[2:-3]
        if vertical_str and vertical_str != 'None':
            verticals_set.add(vertical_str)
    
    # Get verticals from industry field
    industries = db.session.query(
        distinct(Profile.industry)
    ).filter(
        Profile.tenant_id == tenant_id,
        Profile.industry.isnot(None),
        Profile.industry != '',
        Profile.industry != 'None'
    ).all()
    
    for row in industries:
        vertical = row[0] if isinstance(row, tuple) else row
        vertical_str = str(vertical).strip()
        # Remove tuple formatting if present
        if vertical_str.startswith("('") and vertical_str.endswith("',)"):
            vertical_str = vertical_str[2:-3]
        if vertical_str and vertical_str != 'None':
            verticals_set.add(vertical_str)
    
    # Convert to sorted list
    verticals_list = sorted(list(verticals_set))
    
    # If no verticals found in database, return common defaults
    if not verticals_list:
        verticals_list = [
            "Beauty",
            "SaaS / Technology",
            "Healthcare",
            "Financial Services",
            "E-commerce",
            "Manufacturing",
            "Enterprise Software"
        ]
    
    return jsonify({
        "verticals": verticals_list
    }), 200


@bp.route('/functions', methods=['GET'])
@jwt_required()
def get_functions():
    """
    Get available job functions for filtering.
    
    Used In UI: SignalDraftPicker.tsx
    When Called: On component mount to populate the function filter dropdown
    UI Elements: "All Functions" dropdown with options like Marketing, Sales, Operations, Engineering, etc.
    
    Returns:
        200 OK with list of unique job functions from profiles
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get distinct job functions from profiles
    # Functions come from job_title field
    # Extract function from job titles (e.g., "VP of Marketing" -> "Marketing")
    functions_set = set()
    
    # Get all job titles
    job_titles = db.session.query(
        distinct(Profile.job_title)
    ).filter(
        Profile.tenant_id == tenant_id,
        Profile.job_title.isnot(None),
        Profile.job_title != '',
        Profile.job_title != 'None'
    ).all()
    
    # Common function keywords to extract from job titles (ordered by specificity)
    function_keywords = [
        "Marketing", "Sales", "Operations", "Engineering", "Finance", "HR",
        "Human Resources", "Product", "Design", "Customer Success", "Support",
        "Business Development", "Strategy", "Consulting", "Legal", "Compliance",
        "IT", "Information Technology", "Data", "Analytics", "Research",
        "Development", "Manufacturing", "Supply Chain", "Logistics", "Procurement",
        "Quality", "Safety", "Training", "Education", "Content", "Communications",
        "Public Relations", "PR", "Media", "Advertising", "Brand", "Digital",
        "E-commerce", "Retail", "Healthcare", "Medical", "Pharmaceutical", "Biotech"
    ]
    
    # Common prefixes that indicate a function follows
    function_prefixes = [
        "vp of", "vice president of", "director of", "head of", "manager of",
        "lead", "senior", "junior", "chief", "executive", "assistant"
    ]
    
    for row in job_titles:
        job_title = row[0] if isinstance(row, tuple) else row
        job_title_str = str(job_title).strip()
        
        # Remove tuple formatting if present
        if job_title_str.startswith("('") and job_title_str.endswith("',)"):
            job_title_str = job_title_str[2:-3]
        
        if job_title_str and job_title_str != 'None':
            job_title_lower = job_title_str.lower()
            found_function = None
            
            # First, try to find function keywords in the job title
            for keyword in function_keywords:
                keyword_lower = keyword.lower()
                # Check if keyword appears as a whole word or after a prefix
                if keyword_lower in job_title_lower:
                    # Make sure it's not part of another word
                    keyword_pos = job_title_lower.find(keyword_lower)
                    if keyword_pos >= 0:
                        # Check if it's a whole word (preceded by space or start, followed by space or end)
                        before = job_title_lower[keyword_pos - 1] if keyword_pos > 0 else ' '
                        after_pos = keyword_pos + len(keyword_lower)
                        after = job_title_lower[after_pos] if after_pos < len(job_title_lower) else ' '
                        if (before in [' ', '-', '/', '&', '(', 'of '] or keyword_pos == 0) and \
                           (after in [' ', '-', '/', '&', ')', ',', ''] or after_pos >= len(job_title_lower)):
                            found_function = keyword
                            break
            
            # If no keyword found, try to extract function after common prefixes
            if not found_function:
                for prefix in function_prefixes:
                    if prefix in job_title_lower:
                        parts = job_title_lower.split(prefix, 1)
                        if len(parts) > 1:
                            potential_function = parts[1].strip()
                            # Remove common suffixes
                            for suffix in [' manager', ' director', ' lead', ' specialist', ' analyst', ' coordinator']:
                                if potential_function.endswith(suffix):
                                    potential_function = potential_function[:-len(suffix)].strip()
                            # Only use if it's a reasonable length and looks like a function
                            if potential_function and len(potential_function) <= 30 and len(potential_function) >= 3:
                                # Capitalize properly
                                found_function = potential_function.title()
                                break
            
            # If still no function found and job title is short, use it as-is
            if not found_function and len(job_title_str) <= 25:
                # Skip if it contains executive titles
                if not any(exec_title in job_title_lower for exec_title in ['ceo', 'cto', 'cfo', 'coo', 'president', 'founder', 'owner']):
                    found_function = job_title_str
            
            if found_function:
                functions_set.add(found_function)
    
    # Convert to sorted list
    functions_list = sorted(list(functions_set))
    
    # If no functions found in database, return common defaults
    if not functions_list:
        functions_list = [
            "Marketing",
            "Sales",
            "Operations",
            "Engineering",
            "Finance",
            "HR"
        ]
    
    return jsonify({
        "functions": functions_list
    }), 200
