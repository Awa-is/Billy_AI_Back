import csv
import io
import json
import re
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import jwt_required, get_jwt
from urllib.parse import urlparse
from sqlalchemy import or_

from app.extensions import db
from app.models.profile import Profile
from app.models.campaign import CampaignProfile
from app.models.email import Email

bp = Blueprint('profiles', __name__)


def _profile_to_dict(profile):
    """Convert Profile model to dictionary for API response."""
    # Parse JSON fields if they exist
    experiences = None
    skills = None
    educations = None
    
    if profile.experiences:
        try:
            experiences = json.loads(profile.experiences)
        except (json.JSONDecodeError, TypeError):
            experiences = None
    
    if profile.skills:
        try:
            skills = json.loads(profile.skills)
        except (json.JSONDecodeError, TypeError):
            skills = None
    
    if profile.educations:
        try:
            educations = json.loads(profile.educations)
        except (json.JSONDecodeError, TypeError):
            educations = None
    
    return {
        "profile_id": profile.profile_id,
        "tenant_id": profile.tenant_id,
        "person_name": profile.person_name,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "full_name": profile.full_name,
        "headline": profile.headline,
        "about": profile.about,
        "linkedin_url": profile.linkedin_url,
        "linkedin_public_url": profile.linkedin_public_url,
        "linkedin_id": profile.linkedin_id,
        "public_identifier": profile.public_identifier,
        "urn": profile.urn,
        "status": profile.status,
        "email": profile.email,
        "phone": profile.phone,
        "mobile_number": profile.mobile_number,
        "company": profile.company,
        "company_name": profile.company_name,
        "company_industry": profile.company_industry,
        "company_website": profile.company_website,
        "company_linkedin": profile.company_linkedin,
        "company_founded_in": profile.company_founded_in,
        "company_size": profile.company_size,
        "job_title": profile.job_title,
        "job_started_on": profile.job_started_on,
        "job_location": profile.job_location,
        "job_still_working": profile.job_still_working,
        "location": profile.location,
        "address_country_only": profile.address_country_only,
        "address_with_country": profile.address_with_country,
        "address_without_country": profile.address_without_country,
        "industry": profile.industry,
        "connections": profile.connections,
        "followers": profile.followers,
        "profile_pic": profile.profile_pic,
        "profile_pic_high_quality": profile.profile_pic_high_quality,
        "background_pic": profile.background_pic,
        "is_premium": profile.is_premium,
        "is_verified": profile.is_verified,
        "is_job_seeker": profile.is_job_seeker,
        "is_retired": profile.is_retired,
        "is_creator": profile.is_creator,
        "is_influencer": profile.is_influencer,
        "experiences": experiences,
        "skills": skills,
        "educations": educations,
        "scraped_at": profile.scraped_at.isoformat() if profile.scraped_at else None,
        "created_at": profile.created_at.isoformat() if profile.created_at else None
    }


@bp.route('', methods=['GET'])
@jwt_required()
def list_profiles():
    """
    List all profiles for the current tenant with filtering, search, pagination, and sorting.
    
    Query Parameters:
        - page: int (default: 1)
        - limit: int (default: 20, max: 100)
        - status: str (url_only, scraped, scraping_failed)
        - company: str (filter by company name)
        - location: str (filter by location)
        - industry: str (filter by industry)
        - search: str (search in person_name, headline, company - case-insensitive, partial match)
        - sort: str (created_at, person_name, scraped_at - default: created_at)
        - order: str (asc, desc - default: desc)
    
    Returns:
        - profiles: array of profile objects
        - pagination: {page, limit, total, pages}
        - stats: {total, scraped, pending, failed}
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("List profiles: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"List profiles: Request for tenant_id={tenant_id}")
    
    # Parse pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1
        current_app.logger.debug(f"List profiles: Invalid page parameter, defaulting to 1")
    
    try:
        limit = int(request.args.get('limit', 20))
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100
    except (ValueError, TypeError):
        limit = 20
        current_app.logger.debug(f"List profiles: Invalid limit parameter, defaulting to 20")
    
    # Parse sorting parameters
    sort_field = request.args.get('sort', 'created_at').strip().lower()
    sort_order = request.args.get('order', 'desc').strip().lower()
    
    # Validate sort field
    valid_sort_fields = {'created_at', 'person_name', 'scraped_at'}
    if sort_field not in valid_sort_fields:
        sort_field = 'created_at'
        current_app.logger.debug(f"List profiles: Invalid sort field, defaulting to created_at")
    
    # Validate sort order
    if sort_order not in {'asc', 'desc'}:
        sort_order = 'desc'
        current_app.logger.debug(f"List profiles: Invalid sort order, defaulting to desc")
    
    # Build base query with tenant filter
    query = Profile.query.filter_by(tenant_id=tenant_id)
    
    # Apply filters
    status_filter = request.args.get('status', '').strip()
    if status_filter and status_filter in ['url_only', 'scraped', 'scraping_failed']:
        query = query.filter(Profile.status == status_filter)
        current_app.logger.debug(f"List profiles: Applied status filter={status_filter}")
    
    company_filter = request.args.get('company', '').strip()
    if company_filter:
        query = query.filter(Profile.company.ilike(f'%{company_filter}%'))
        current_app.logger.debug(f"List profiles: Applied company filter={company_filter}")
    
    location_filter = request.args.get('location', '').strip()
    if location_filter:
        query = query.filter(Profile.location.ilike(f'%{location_filter}%'))
        current_app.logger.debug(f"List profiles: Applied location filter={location_filter}")
    
    industry_filter = request.args.get('industry', '').strip()
    if industry_filter:
        query = query.filter(Profile.industry.ilike(f'%{industry_filter}%'))
        current_app.logger.debug(f"List profiles: Applied industry filter={industry_filter}")
    
    # Apply search (case-insensitive, partial match on person_name, headline, company)
    search_term = request.args.get('search', '').strip()
    if search_term:
        search_pattern = f'%{search_term}%'
        query = query.filter(
            or_(
                Profile.person_name.ilike(search_pattern),
                Profile.headline.ilike(search_pattern),
                Profile.company.ilike(search_pattern)
            )
        )
        current_app.logger.debug(f"List profiles: Applied search term={search_term}")
    
    # Get total count (with filters applied) for pagination
    total_count = query.count()
    
    # Get stats for all profiles (without filters) - for overall tenant stats
    # Stats show total counts across all profiles for the tenant
    all_profiles_query = Profile.query.filter_by(tenant_id=tenant_id)
    total_all = all_profiles_query.count()
    scraped_count = all_profiles_query.filter(Profile.status == 'scraped').count()
    pending_count = all_profiles_query.filter(Profile.status == 'url_only').count()
    failed_count = all_profiles_query.filter(Profile.status == 'scraping_failed').count()
    
    current_app.logger.debug(
        f"List profiles: Stats - total={total_all}, scraped={scraped_count}, "
        f"pending={pending_count}, failed={failed_count}"
    )
    
    # Apply sorting
    sort_column = getattr(Profile, sort_field)
    if sort_order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    current_app.logger.debug(f"List profiles: Sorting by {sort_field} {sort_order}")
    
    # Apply pagination
    offset = (page - 1) * limit
    profiles = query.offset(offset).limit(limit).all()
    
    current_app.logger.debug(
        f"List profiles: Returning page={page}, limit={limit}, "
        f"total={total_count}, profiles_returned={len(profiles)}"
    )
    
    # Calculate total pages
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
    
    # Convert profiles to dictionaries
    profiles_data = [_profile_to_dict(profile) for profile in profiles]
    
    return jsonify({
        "profiles": profiles_data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "pages": total_pages
        },
        "stats": {
            "total": total_all,
            "scraped": scraped_count,
            "pending": pending_count,
            "failed": failed_count
        }
    }), 200


@bp.route('/<profile_id>', methods=['GET'])
@jwt_required()
def get_profile(profile_id):
    """
    Retrieve a single profile by its profile ID.
    
    Requirements:
    - JWT authentication required
    - Profile must exist and belong to the requesting tenant
    
    Returns:
    - 200: Profile object using _profile_to_dict()
    - 401: Unauthorized (JWT missing or invalid)
    - 403: Forbidden (profile belongs to different tenant)
    - 404: Profile not found
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        current_app.logger.warning("Get profile: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Get profile: Request for profile_id={profile_id}, tenant_id={tenant_id}")
    
    # Query profile by profile_id
    profile = Profile.query.filter_by(profile_id=profile_id).first()
    
    if not profile:
        current_app.logger.warning(f"Get profile: Profile not found profile_id={profile_id}, tenant_id={tenant_id}")
        return jsonify({"error": "Profile not found"}), 404
    
    # Verify profile belongs to requesting tenant
    if profile.tenant_id != tenant_id:
        current_app.logger.warning(
            f"Get profile: Forbidden - profile belongs to different tenant. "
            f"profile_id={profile_id}, profile_tenant_id={profile.tenant_id}, requesting_tenant_id={tenant_id}"
        )
        return jsonify({"error": "Forbidden"}), 403
    
    current_app.logger.debug(
        f"Get profile: Successfully retrieved profile_id={profile_id}, "
        f"person_name={profile.person_name}, tenant_id={tenant_id}"
    )
    
    # Return profile using _profile_to_dict() helper function
    return jsonify(_profile_to_dict(profile)), 200


def _normalize_linkedin_url(raw_url: str):
    """Validate and normalize LinkedIn profile URLs."""
    if not raw_url:
        return None, None, "linkedin_url cannot be empty"

    url = raw_url.strip()
    if not url:
        return None, None, "linkedin_url cannot be empty"

    if not url.lower().startswith(('http://', 'https://')):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
    except ValueError:
        return None, None, "Invalid linkedin_url format"

    netloc = parsed.netloc.lower()
    if netloc not in ('linkedin.com', 'www.linkedin.com'):
        return None, None, "linkedin_url must point to linkedin.com"

    path = parsed.path.strip('/')
    if not path:
        return None, None, "linkedin_url must include profile path"

    segments = path.split('/')
    section = segments[0].lower()
    if section not in ('in', 'pub', 'profile', 'sales'):
        return None, None, "linkedin_url must point to a profile page"

    username = segments[1] if len(segments) > 1 else ''
    if not username:
        return None, None, "linkedin_url must include a profile username"

    username = username.strip()
    normalized = f"https://www.linkedin.com/{section}/{username}"
    return normalized, username, None


@bp.route('', methods=['POST'])
@jwt_required()
def add_profile():
    """Allow tenants to submit a LinkedIn profile URL manually."""
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    linkedin_url = data.get('linkedin_url')
    if linkedin_url is None:
        return jsonify({"error": "linkedin_url required"}), 400

    normalized_url, username, error = _normalize_linkedin_url(linkedin_url)
    if error:
        return jsonify({"error": error}), 400

    current_app.logger.debug(
        "Profiles: tenant=%s submitted URL=%s normalized=%s username=%s",
        tenant_id,
        linkedin_url,
        normalized_url,
        username,
    )

    existing = Profile.query.filter_by(
        tenant_id=tenant_id,
        linkedin_url=normalized_url
    ).first()
    if existing:
        return jsonify({
            "error": "Profile already exists",
            "profile_id": existing.profile_id
        }), 400

    profile = Profile(
        tenant_id=tenant_id,
        linkedin_url=normalized_url,
        status='url_only'
    )
    db.session.add(profile)
    db.session.commit()

    response = {
        "profile_id": profile.profile_id,
        "tenant_id": profile.tenant_id,
        "linkedin_url": profile.linkedin_url,
        "username": username,
        "status": profile.status,
        "person_name": profile.person_name,
        "headline": profile.headline,
        "created_at": profile.created_at.isoformat() if profile.created_at else None
    }
    return jsonify({"profile": response}), 201


def _parse_csv(file_storage):
    content = file_storage.read()
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig')
    stream = io.StringIO(content)
    try:
        reader = csv.reader(stream)
        rows = [row for row in reader if any(cell.strip() for cell in row)]
    except csv.Error:
        return None, "Invalid CSV format"
    return rows, None


def _extract_url_from_row(row, header_map=None):
    if header_map:
        idx = header_map.get('linkedin_url')
        if idx is None or idx >= len(row):
            return None, None, "linkedin_url column missing"
        name = None
        if 'name' in header_map:
            name_idx = header_map['name']
            if name_idx is not None and name_idx < len(row):
                name = row[name_idx].strip() or None
        return row[idx], name, None

    # simple CSV: first column only
    return row[0] if row else '', None, None


def _validate_email(email_str):
    """
    Validate email address format (RFC 5322 compliant).
    
    Args:
        email_str: Email address string to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not email_str or not email_str.strip():
        return False, "Email cannot be empty"
    
    email_str = email_str.strip()
    
    # RFC 5322 compliant regex pattern (simplified but covers most cases)
    # This pattern matches: local-part@domain
    # Local part: alphanumeric, dots, hyphens, underscores, plus signs
    # Domain: alphanumeric, dots, hyphens
    pattern = r'^[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email_str):
        return False, "Invalid email format"
    
    # Additional checks
    if len(email_str) > 255:
        return False, "Email address too long (max 255 characters)"
    
    # Check for consecutive dots
    if '..' in email_str:
        return False, "Invalid email format (consecutive dots not allowed)"
    
    # Check that @ appears only once
    if email_str.count('@') != 1:
        return False, "Invalid email format (must contain exactly one @)"
    
    # Split and validate parts
    parts = email_str.split('@')
    local_part = parts[0]
    domain = parts[1]
    
    if not local_part or len(local_part) > 64:
        return False, "Invalid email format (local part too long or empty)"
    
    if not domain or len(domain) > 255:
        return False, "Invalid email format (domain too long or empty)"
    
    # Domain must have at least one dot
    if '.' not in domain:
        return False, "Invalid email format (domain must contain a dot)"
    
    return True, None


def _extract_lead_from_row(row, header_map=None):
    """
    Extract linkedin_url, email, name, and notes from CSV row.
    
    Args:
        row: CSV row as list
        header_map: Dictionary mapping column names to indices
        
    Returns:
        tuple: (linkedin_url, email, name, notes, error_message)
    """
    if not header_map:
        # Simple CSV format: first column is linkedin_url, second is email
        if len(row) < 2:
            return None, None, None, None, "CSV must contain 'linkedin_url' and 'email' columns"
        linkedin_url = row[0].strip() if len(row) > 0 else ''
        email = row[1].strip() if len(row) > 1 else ''
        name = row[2].strip() if len(row) > 2 else None
        notes = row[3].strip() if len(row) > 3 else None
        return linkedin_url, email, name, notes, None
    
    # Header-based CSV
    linkedin_idx = header_map.get('linkedin_url')
    email_idx = header_map.get('email')
    
    if linkedin_idx is None:
        return None, None, None, None, "CSV must contain 'linkedin_url' column"
    if email_idx is None:
        return None, None, None, None, "CSV must contain 'email' column"
    
    if linkedin_idx >= len(row):
        return None, None, None, None, "linkedin_url column missing or out of bounds"
    if email_idx >= len(row):
        return None, None, None, None, "email column missing or out of bounds"
    
    linkedin_url = row[linkedin_idx].strip() if linkedin_idx < len(row) else ''
    email = row[email_idx].strip() if email_idx < len(row) else ''
    
    name = None
    if 'name' in header_map:
        name_idx = header_map['name']
        if name_idx is not None and name_idx < len(row):
            name_val = row[name_idx].strip()
            name = name_val if name_val else None
    
    notes = None
    if 'notes' in header_map:
        notes_idx = header_map['notes']
        if notes_idx is not None and notes_idx < len(row):
            notes_val = row[notes_idx].strip()
            notes = notes_val if notes_val else None
    
    return linkedin_url, email, name, notes, None


@bp.route('/bulk-upload', methods=['POST'])
@jwt_required()
def bulk_upload_profiles():
    """Allow tenants to upload multiple LinkedIn profile URLs via CSV."""
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    uploaded_file = request.files.get('file')
    if not uploaded_file:
        return jsonify({"error": "No file provided"}), 400

    if not uploaded_file.filename.lower().endswith('.csv'):
        return jsonify({"error": "File must be CSV format"}), 400

    rows, parse_error = _parse_csv(uploaded_file)
    if parse_error:
        return jsonify({"error": parse_error}), 400

    if not rows:
        return jsonify({"error": "Invalid CSV format"}), 400

    if len(rows) > 1000:
        return jsonify({"error": "Maximum 1000 profiles allowed"}), 400

    header_map = None
    first_row_lower = [cell.strip().lower() for cell in rows[0]]
    if 'linkedin_url' in first_row_lower:
        header_map = {name: idx for idx, name in enumerate(first_row_lower)}
        data_rows = rows[1:]
    else:
        data_rows = rows

    if not data_rows:
        return jsonify({"error": "No profile rows found"}), 400

    normalized_existing = {
        p.linkedin_url for p in Profile.query.filter_by(tenant_id=tenant_id).all()
    }
    normalized_in_batch = set()
    to_insert = []
    errors = []
    skipped = 0

    for idx, row in enumerate(data_rows, start=1):
        raw_url, person_name, row_error = _extract_url_from_row(row, header_map)
        if row_error:
            errors.append({"row": idx, "error": row_error})
            continue

        normalized_url, username, normalize_error = _normalize_linkedin_url(raw_url)
        if normalize_error:
            errors.append({"row": idx, "error": normalize_error})
            continue

        if normalized_url in normalized_existing or normalized_url in normalized_in_batch:
            skipped += 1
            continue

        profile = Profile(
            tenant_id=tenant_id,
            linkedin_url=normalized_url,
            status='url_only',
            person_name=person_name
        )
        to_insert.append(profile)
        normalized_in_batch.add(normalized_url)

    if not to_insert and not errors and skipped == 0:
        return jsonify({"error": "No valid profiles found in CSV"}), 400

    added = 0
    try:
        if to_insert:
            db.session.add_all(to_insert)
            db.session.commit()
            added = len(to_insert)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Bulk upload failed: %s", exc)
        return jsonify({"error": "Database error occurred"}), 500

    summary = {
        "added": added,
        "skipped": skipped,
        "failed": len(errors),
        "errors": errors,
        "total_rows": len(data_rows)
    }
    return jsonify(summary), 201


@bp.route('/bulk-upload/template', methods=['GET'])
@jwt_required()
def download_bulk_template():
    """Provide CSV template for bulk profile uploads."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['linkedin_url', 'name', 'notes'])
    writer.writerow(['https://www.linkedin.com/in/example/', 'Jane Doe', 'VP Marketing'])
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=profile_upload_template.csv'
    return response


@bp.route('/bulk-upload-leads', methods=['POST'])
@jwt_required()
def bulk_upload_leads():
    """
    Allow tenants to upload multiple leads (LinkedIn URLs with email addresses) via CSV.
    
    CSV Format:
        - Required columns: linkedin_url, email
        - Optional columns: name, notes
    
    Query Parameters:
        - force_update: boolean (default: false) - If true, updates existing profiles even if they have an email
    
    Returns:
        Summary with created, updated, skipped, failed counts and error details
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Bulk upload leads: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Bulk upload leads: Request received for tenant_id={tenant_id}")
    
    # Check for force_update flag
    force_update = request.args.get('force_update', 'false').lower() == 'true'
    
    # Check for template preference
    template_id = request.args.get('template_id')
    if template_id and not template_id.strip():
        template_id = None
        
    current_app.logger.debug(f"Bulk upload leads: force_update={force_update}, template_id={template_id}")
    
    # Validate file upload
    uploaded_file = request.files.get('file')
    if not uploaded_file:
        current_app.logger.warning("Bulk upload leads: No file provided")
        return jsonify({"error": "No file provided"}), 400
    
    if not uploaded_file.filename.lower().endswith('.csv'):
        current_app.logger.warning(f"Bulk upload leads: Invalid file type - {uploaded_file.filename}")
        return jsonify({"error": "File must be CSV format"}), 400
    
    # Parse CSV
    rows, parse_error = _parse_csv(uploaded_file)
    if parse_error:
        current_app.logger.warning(f"Bulk upload leads: CSV parse error - {parse_error}")
        return jsonify({"error": parse_error}), 400
    
    if not rows:
        current_app.logger.warning("Bulk upload leads: Empty CSV file")
        return jsonify({"error": "Invalid CSV format"}), 400
    
    # Check row limit
    if len(rows) > 1000:
        current_app.logger.warning(f"Bulk upload leads: Too many rows - {len(rows)}")
        return jsonify({"error": "Maximum 1000 leads allowed"}), 400
    
    current_app.logger.debug(f"Bulk upload leads: Parsed {len(rows)} rows from CSV")
    
    # Detect header row
    header_map = None
    first_row_lower = [cell.strip().lower() for cell in rows[0]]
    has_linkedin = 'linkedin_url' in first_row_lower
    has_email = 'email' in first_row_lower
    
    if has_linkedin and has_email:
        # Header row detected with both required columns
        header_map = {name: idx for idx, name in enumerate(first_row_lower)}
        data_rows = rows[1:]
        current_app.logger.debug("Bulk upload leads: Detected header row with linkedin_url and email")
    elif has_linkedin or has_email:
        # Header row detected but missing required column
        if not has_linkedin:
            current_app.logger.warning("Bulk upload leads: Header row missing linkedin_url column")
            return jsonify({"error": "CSV must contain 'linkedin_url' and 'email' columns"}), 400
        if not has_email:
            current_app.logger.warning("Bulk upload leads: Header row missing email column")
            return jsonify({"error": "CSV must contain 'linkedin_url' and 'email' columns"}), 400
    else:
        # No header row - assume first two columns are linkedin_url and email
        data_rows = rows
        current_app.logger.debug("Bulk upload leads: No header row detected, using first two columns")
    
    if not data_rows:
        current_app.logger.warning("Bulk upload leads: No data rows found in CSV")
        return jsonify({"error": "No profile rows found"}), 400
    
    # Validate required columns exist (for header-based CSV)
    if header_map:
        if 'linkedin_url' not in header_map:
            current_app.logger.warning("Bulk upload leads: Missing linkedin_url column")
            return jsonify({"error": "CSV must contain 'linkedin_url' and 'email' columns"}), 400
        if 'email' not in header_map:
            current_app.logger.warning("Bulk upload leads: Missing email column")
            return jsonify({"error": "CSV must contain 'linkedin_url' and 'email' columns"}), 400
    
    current_app.logger.debug(f"Bulk upload leads: Processing {len(data_rows)} data rows")
    
    # Get existing profiles for this tenant (optimized query)
    existing_profiles = Profile.query.filter_by(tenant_id=tenant_id).all()
    existing_profiles_map = {p.linkedin_url: p for p in existing_profiles}
    current_app.logger.debug(f"Bulk upload leads: Found {len(existing_profiles)} existing profiles for tenant")
    
    # Track processing
    normalized_in_batch = set()
    to_insert = []
    to_update = []
    errors = []
    skipped = 0
    existing_unprocessed = []  # Track existing profiles that need processing but no update
    
    # Process each row
    for idx, row in enumerate(data_rows, start=1):
        current_app.logger.debug(f"Bulk upload leads: Processing row {idx}")
        
        # Extract data from row
        linkedin_url, email, name, notes, extract_error = _extract_lead_from_row(row, header_map)
        if extract_error:
            current_app.logger.warning(f"Bulk upload leads: Row {idx} extraction error - {extract_error}")
            errors.append({"row": idx, "error": extract_error})
            continue
        
        # Validate LinkedIn URL
        if not linkedin_url or not linkedin_url.strip():
            current_app.logger.warning(f"Bulk upload leads: Row {idx} - empty linkedin_url")
            errors.append({"row": idx, "error": "linkedin_url cannot be empty"})
            continue
        
        normalized_url, username, normalize_error = _normalize_linkedin_url(linkedin_url)
        if normalize_error:
            current_app.logger.warning(f"Bulk upload leads: Row {idx} LinkedIn URL validation error - {normalize_error}")
            errors.append({"row": idx, "error": normalize_error})
            continue
        
        # Validate email
        if not email or not email.strip():
            current_app.logger.warning(f"Bulk upload leads: Row {idx} - empty email")
            errors.append({"row": idx, "error": "email cannot be empty"})
            continue
        
        is_valid_email, email_error = _validate_email(email)
        if not is_valid_email:
            current_app.logger.warning(f"Bulk upload leads: Row {idx} email validation error - {email_error}")
            errors.append({"row": idx, "error": email_error})
            continue
        
        email = email.strip()
        
        # Check for duplicates within batch
        if normalized_url in normalized_in_batch:
            current_app.logger.debug(f"Bulk upload leads: Row {idx} - duplicate URL in batch, skipping")
            skipped += 1
            continue
        
        normalized_in_batch.add(normalized_url)
        
        # Check if profile exists
        existing_profile = existing_profiles_map.get(normalized_url)
        
        if existing_profile:
            # Profile exists
            current_app.logger.debug(
                f"Bulk upload leads: Row {idx} - profile exists, "
                f"current_email={existing_profile.email}, new_email={email}"
            )
            
            # Use a flag to track if we made changes
            updated = False
            
            # Update assigned template if provided
            if template_id and existing_profile.assigned_template_id != template_id:
                existing_profile.assigned_template_id = template_id
                updated = True
                current_app.logger.debug(f"Bulk upload leads: Row {idx} - updated assigned_template_id")

            # Check if we should update email/name
            if not existing_profile.email or force_update:
                existing_profile.email = email
                if name:
                    existing_profile.person_name = name
                updated = True
            
            if updated:
                to_update.append(existing_profile)
                current_app.logger.debug(f"Bulk upload leads: Row {idx} - queued for update")
            else:
                current_app.logger.debug(
                    f"Bulk upload leads: Row {idx} - profile up to date, skipping"
                )
                skipped += 1
                # If profile needs processing (no data yet), queue it
                if existing_profile.status in ['url_only', 'scraping_failed']:
                    existing_unprocessed.append(existing_profile)
                continue
        else:
            # Create new profile
            profile = Profile(
                tenant_id=tenant_id,
                linkedin_url=normalized_url,
                email=email,
                status='url_only',
                person_name=name,
                assigned_template_id=template_id
            )
            to_insert.append(profile)
            current_app.logger.debug(f"Bulk upload leads: Row {idx} - queued for creation")
    
    current_app.logger.debug(
        f"Bulk upload leads: Processing complete - "
        f"to_insert={len(to_insert)}, to_update={len(to_update)}, "
        f"skipped={skipped}, errors={len(errors)}"
    )
    
    # Validate we have something to process
    if not to_insert and not to_update and not errors and skipped == 0:
        current_app.logger.warning("Bulk upload leads: No valid leads found in CSV")
        return jsonify({"error": "No valid leads found in CSV"}), 400
    
    # Perform batch insert/update in transaction
    try:
        if to_insert:
            current_app.logger.debug(f"Bulk upload leads: Inserting {len(to_insert)} new profiles")
            db.session.add_all(to_insert)
        
        if to_update:
            current_app.logger.debug(f"Bulk upload leads: Updating {len(to_update)} existing profiles")
            # Profiles are already in session, just need to commit
        
        db.session.commit()
        current_app.logger.info(
            f"Bulk upload leads: Successfully processed - "
            f"created={len(to_insert)}, updated={len(to_update)}, "
            f"skipped={skipped}, failed={len(errors)}"
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(f"Bulk upload leads: Database error - {exc}")
        return jsonify({"error": "Database error occurred"}), 500
    
    # Build summary response
    summary = {
        "created": len(to_insert),
        "updated": len(to_update),
        "skipped": skipped,
        "failed": len(errors),
        "errors": errors,
        "total_rows": len(data_rows)
    }
    
    # Automatically start background processing for newly created/updated profiles
    profile_ids_to_process = []
    if to_insert:
        profile_ids_to_process.extend([p.profile_id for p in to_insert])
    if to_update:
        profile_ids_to_process.extend([p.profile_id for p in to_update])
    if existing_unprocessed:
        profile_ids_to_process.extend([p.profile_id for p in existing_unprocessed])
    
    job_id = None
    if profile_ids_to_process:
        try:
            # Import here to avoid circular imports
            from app.tasks.scraper import process_lead_upload
            from app.models.job import Job
            import uuid
            
            # Create job record
            job_id = str(uuid.uuid4())
            job = Job(
                job_id=job_id,
                tenant_id=tenant_id,
                job_type='lead_processing',
                status='pending',
                total_items=len(profile_ids_to_process),
                result_data=json.dumps({"profile_ids": profile_ids_to_process})
            )
            db.session.add(job)
            db.session.commit()
            
            current_app.logger.info(
                f"Bulk upload leads: Starting background processing job_id={job_id} "
                f"for {len(profile_ids_to_process)} profiles"
            )
            
            # Check if Celery is properly configured
            try:
                from app.tasks.celery_app import celery_app
                broker_url = celery_app.conf.broker_url
                if not broker_url or broker_url == 'memory://':
                    raise ValueError("Celery broker is not properly configured")
            except Exception as celery_check_error:
                current_app.logger.error(f"Bulk upload leads: Celery configuration error: {str(celery_check_error)}")
                job.status = 'failed'
                job.error_message = f"Celery/Redis not configured: {str(celery_check_error)}"
                job.completed_at = datetime.utcnow()
                db.session.commit()
                # Continue with response - processing will need to be triggered manually
                summary["processing_job_id"] = None
                summary["processing_error"] = "Background processing not available - Celery/Redis not configured"
                current_app.logger.debug(f"Bulk upload leads: Returning summary - {summary}")
                return jsonify(summary), 201
            
            # Start async Celery task
            try:
                task = process_lead_upload.apply_async(
                    args=[job_id, tenant_id, profile_ids_to_process],
                    task_id=job_id
                )
                current_app.logger.info(
                    f"Bulk upload leads: Started background processing job_id={job_id}, "
                    f"task_id={task.id}, profiles={len(profile_ids_to_process)}"
                )
                summary["processing_job_id"] = job_id
                summary["processing_status_url"] = f"/api/jobs/{job_id}"
            except Exception as celery_error:
                error_msg = str(celery_error)
                current_app.logger.error(f"Bulk upload leads: Failed to start background processing: {error_msg}")
                job.status = 'failed'
                job.error_message = f"Failed to start processing: {error_msg}"
                job.completed_at = datetime.utcnow()
                db.session.commit()
                summary["processing_job_id"] = None
                summary["processing_error"] = f"Failed to start background processing: {error_msg}"
        except Exception as e:
            current_app.logger.exception(f"Bulk upload leads: Error starting background processing: {str(e)}")
            # Don't fail the upload if background processing fails to start
            summary["processing_job_id"] = None
            summary["processing_error"] = f"Failed to start background processing: {str(e)}"
    
    current_app.logger.debug(f"Bulk upload leads: Returning summary - {summary}")
    return jsonify(summary), 201


@bp.route('/bulk-upload-leads/template', methods=['GET'])
@jwt_required()
def download_bulk_leads_template():
    """Provide CSV template for bulk leads upload (LinkedIn URLs with emails)."""
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Bulk upload leads template: Request from tenant_id={tenant_id}")
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['linkedin_url', 'email', 'name', 'notes'])
    writer.writerow([
        'https://www.linkedin.com/in/example/',
        'example@email.com',
        'Jane Doe',
        'VP Marketing - interested in product demo'
    ])
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=leads_upload_template.csv'
    
    current_app.logger.debug("Bulk upload leads template: Template generated successfully")
    return response


@bp.route('/scrape', methods=['POST'])
@jwt_required()
def scrape_all_profiles():
    """
    Scrape all profiles with status='url_only' for the current tenant.
    
    Returns job_id immediately (async task). Processes up to 50 profiles per job.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Profile scrape: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Profile scrape: Starting scrape for tenant_id={tenant_id}")
    
    # Import here to avoid circular imports
    from app.tasks.scraper import scrape_profiles
    from app.models.job import Job
    import uuid
    
    try:
        # Get profiles count and limit in single optimized query
        profiles_query = Profile.query.filter_by(
            tenant_id=tenant_id,
            status='url_only'
        )
        profile_count = profiles_query.count()
        
        if profile_count == 0:
            current_app.logger.debug(f"Profile scrape: No profiles to scrape for tenant_id={tenant_id}")
            return jsonify({
                "message": "No profiles to scrape",
                "profiles_found": 0
            }), 200
        
        # Create job record
        job_id = str(uuid.uuid4())
        batch_size = min(profile_count, 50)  # Batch limit: 50
        job = Job(
            job_id=job_id,
            tenant_id=tenant_id,
            job_type='profile_scrape',
            status='pending',
            total_items=batch_size
        )
        db.session.add(job)
        db.session.commit()
        
        current_app.logger.debug(f"Profile scrape: Created job_id={job_id} for tenant_id={tenant_id}")
        
        # Check if Celery is properly configured before starting task
        try:
            from app.tasks.celery_app import celery_app
            # Check if broker is configured
            broker_url = celery_app.conf.broker_url
            if not broker_url or broker_url == 'memory://':
                raise ValueError("Celery broker is not properly configured. Please check Redis connection.")
        except Exception as celery_check_error:
            current_app.logger.error(f"Profile scrape: Celery configuration error: {str(celery_check_error)}")
            job.status = 'failed'
            job.error_message = f"Celery/Redis not configured: {str(celery_check_error)}"
            job.completed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                "error": "Celery/Redis service not available",
                "details": str(celery_check_error),
                "message": "Please ensure Redis is running and CELERY_BROKER_URL is configured"
            }), 503
        
        # Start async Celery task
        try:
            task = scrape_profiles.delay(job_id, tenant_id, profile_ids=None)
            current_app.logger.info(f"Profile scrape: Started job_id={job_id}, task_id={task.id}, tenant_id={tenant_id}")
        except Exception as celery_error:
            # Handle Celery connection errors specifically
            error_msg = str(celery_error)
            if 'Redis' in error_msg or 'broker' in error_msg.lower() or 'connection' in error_msg.lower():
                current_app.logger.error(f"Profile scrape: Celery/Redis connection error: {error_msg}")
                job.status = 'failed'
                job.error_message = f"Celery/Redis connection failed: {error_msg}"
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return jsonify({
                    "error": "Celery/Redis connection failed",
                    "details": error_msg,
                    "message": "Please ensure Redis is running and accessible"
                }), 503
            else:
                # Re-raise other errors to be caught by outer exception handler
                raise
        
        return jsonify({
            "message": "Scraping job started",
            "job_id": job_id,
            "profiles_found": profile_count,
            "profiles_in_batch": batch_size,
            "status_url": f"/api/jobs/{job_id}"
        }), 202
        
    except Exception as e:
        current_app.logger.exception(f"Profile scrape: Error starting job for tenant_id={tenant_id}: {str(e)}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to start scraping job",
            "details": str(e)
        }), 500


@bp.route('/<profile_id>/scrape', methods=['POST'])
@jwt_required()
def scrape_single_profile(profile_id):
    """
    Scrape a single profile by ID.
    
    Returns job_id immediately (async task).
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Profile scrape: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Profile scrape: Starting single profile scrape profile_id={profile_id}, tenant_id={tenant_id}")
    
    # Verify profile exists and belongs to tenant
    profile = Profile.query.filter_by(profile_id=profile_id).first()
    if not profile:
        current_app.logger.warning(f"Profile scrape: Profile not found profile_id={profile_id}")
        return jsonify({"error": "Profile not found"}), 404
    
    if profile.tenant_id != tenant_id:
        current_app.logger.warning(f"Profile scrape: Forbidden - profile belongs to different tenant profile_id={profile_id}")
        return jsonify({"error": "Forbidden"}), 403
    
    if profile.status != 'url_only':
        current_app.logger.debug(f"Profile scrape: Profile already scraped profile_id={profile_id}, status={profile.status}")
        return jsonify({
            "message": "Profile already scraped",
            "profile_id": profile_id,
            "status": profile.status
        }), 200
    
    # Import here to avoid circular imports
    from app.tasks.scraper import scrape_profiles
    from app.models.job import Job
    import uuid
    
    try:
        # Create job record
        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            tenant_id=tenant_id,
            job_type='profile_scrape',
            status='pending',
            total_items=1
        )
        db.session.add(job)
        db.session.commit()
        
        current_app.logger.debug(f"Profile scrape: Created job_id={job_id} for profile_id={profile_id}")
        
        # Check if Celery is properly configured before starting task
        try:
            from app.tasks.celery_app import celery_app
            # Check if broker is configured
            broker_url = celery_app.conf.broker_url
            if not broker_url or broker_url == 'memory://':
                raise ValueError("Celery broker is not properly configured. Please check Redis connection.")
        except Exception as celery_check_error:
            current_app.logger.error(f"Profile scrape: Celery configuration error: {str(celery_check_error)}")
            job.status = 'failed'
            job.error_message = f"Celery/Redis not configured: {str(celery_check_error)}"
            job.completed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                "error": "Celery/Redis service not available",
                "details": str(celery_check_error),
                "message": "Please ensure Redis is running and CELERY_BROKER_URL is configured"
            }), 503
        
        # Start async Celery task
        try:
            task = scrape_profiles.delay(job_id, tenant_id, profile_ids=[profile_id])
            current_app.logger.info(f"Profile scrape: Started job_id={job_id}, task_id={task.id}, profile_id={profile_id}")
        except Exception as celery_error:
            # Handle Celery connection errors specifically
            error_msg = str(celery_error)
            if 'Redis' in error_msg or 'broker' in error_msg.lower() or 'connection' in error_msg.lower():
                current_app.logger.error(f"Profile scrape: Celery/Redis connection error: {error_msg}")
                job.status = 'failed'
                job.error_message = f"Celery/Redis connection failed: {error_msg}"
                job.completed_at = datetime.utcnow()
                db.session.commit()
                return jsonify({
                    "error": "Celery/Redis connection failed",
                    "details": error_msg,
                    "message": "Please ensure Redis is running and accessible"
                }), 503
            else:
                # Re-raise other errors to be caught by outer exception handler
                raise
        
        return jsonify({
            "message": "Scraping job started",
            "job_id": job_id,
            "profile_id": profile_id,
            "status_url": f"/api/jobs/{job_id}"
        }), 202
        
    except Exception as e:
        current_app.logger.exception(f"Profile scrape: Error starting job for profile_id={profile_id}: {str(e)}")
        db.session.rollback()
        return jsonify({
            "error": "Failed to start scraping job",
            "details": str(e)
        }), 500


@bp.route('/bulk', methods=['DELETE'])
@jwt_required()
def bulk_delete_profiles():
    """
    Bulk delete multiple profiles.
    
    Request body:
        {
            "ids": ["uuid1", "uuid2", ...]
        }
    
    Returns:
        - 200 OK: All profiles deleted successfully
        - 207 Multi-Status: Partial success (some deleted, some failed)
        - 400 Bad Request: Invalid input or all deletions failed
    
    Validation:
        - Maximum 100 items per request
        - All IDs must belong to the requesting tenant
        - Cannot delete profiles linked to campaigns
        - Cannot delete profiles with sent emails
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        current_app.logger.warning("Bulk delete profiles: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Bulk delete profiles: Request for tenant_id={tenant_id}")
    
    # Parse request body
    data = request.get_json() or {}
    profile_ids = data.get('ids', [])
    
    # Validate input
    if not isinstance(profile_ids, list):
        current_app.logger.warning(f"Bulk delete profiles: Invalid input type, expected list, got {type(profile_ids)}")
        return jsonify({"error": "ids must be an array"}), 400
    
    if len(profile_ids) == 0:
        current_app.logger.warning("Bulk delete profiles: Empty ids array")
        return jsonify({"error": "ids array cannot be empty"}), 400
    
    if len(profile_ids) > 100:
        current_app.logger.warning(f"Bulk delete profiles: Too many items, got {len(profile_ids)}, max 100")
        return jsonify({"error": "Cannot delete more than 100 profiles at once"}), 400
    
    current_app.logger.debug(f"Bulk delete profiles: Processing {len(profile_ids)} profile IDs")
    
    # Import models here to avoid circular imports
    from app.models.campaign import CampaignProfile
    from app.models.email import Email
    
    # Track results
    successful = []
    failed = []
    
    try:
        # Fetch all profiles that belong to the tenant
        profiles = Profile.query.filter(
            Profile.profile_id.in_(profile_ids),
            Profile.tenant_id == tenant_id
        ).all()
        
        found_profile_ids = {profile.profile_id for profile in profiles}
        missing_ids = set(profile_ids) - found_profile_ids
        
        # Add missing IDs to failed list
        for missing_id in missing_ids:
            failed.append({
                "id": missing_id,
                "reason": "Profile not found or does not belong to tenant"
            })
            current_app.logger.debug(f"Bulk delete profiles: Profile {missing_id} not found or access denied")
        
        # Check each profile for validation rules
        for profile in profiles:
            profile_id = profile.profile_id
            current_app.logger.debug(f"Bulk delete profiles: Validating profile_id={profile_id}")
            
            # Check if profile is linked to campaigns (prevent deletion if linked)
            campaign_links = CampaignProfile.query.filter_by(profile_id=profile_id).all()
            if campaign_links:
                # Check if any linked campaigns have sent emails
                email_ids = [link.email_id for link in campaign_links if link.email_id]
                if email_ids:
                    sent_emails_count = Email.query.filter(
                        Email.email_id.in_(email_ids),
                        Email.status == 'sent'
                    ).count()
                    
                    if sent_emails_count > 0:
                        failed.append({
                            "id": profile_id,
                            "reason": "Profile is linked to campaigns with sent emails"
                        })
                        current_app.logger.debug(f"Bulk delete profiles: Profile {profile_id} has {sent_emails_count} sent emails in campaigns")
                        continue
                
                # Profile is linked to campaigns (even without sent emails) - prevent deletion
                failed.append({
                    "id": profile_id,
                    "reason": "Profile is linked to campaigns"
                })
                current_app.logger.debug(f"Bulk delete profiles: Profile {profile_id} is linked to campaigns")
                continue
            
            # Check for direct sent emails (not through campaigns)
            direct_sent_emails = Email.query.filter_by(
                profile_id=profile_id,
                status='sent'
            ).first()
            
            if direct_sent_emails:
                failed.append({
                    "id": profile_id,
                    "reason": "Profile has sent emails"
                })
                current_app.logger.debug(f"Bulk delete profiles: Profile {profile_id} has direct sent emails")
                continue
            
            # Profile is safe to delete
            try:
                db.session.delete(profile)
                successful.append({
                    "id": profile_id
                })
                current_app.logger.debug(f"Bulk delete profiles: Profile {profile_id} marked for deletion")
            except Exception as delete_error:
                current_app.logger.error(f"Bulk delete profiles: Error deleting profile {profile_id}: {str(delete_error)}")
                failed.append({
                    "id": profile_id,
                    "reason": f"Database error: {str(delete_error)}"
                })
        
        # Commit all deletions
        if successful:
            try:
                db.session.commit()
                current_app.logger.info(f"Bulk delete profiles: Successfully deleted {len(successful)} profiles")
            except Exception as commit_error:
                current_app.logger.error(f"Bulk delete profiles: Error committing deletions: {str(commit_error)}")
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
            current_app.logger.info(f"Bulk delete profiles: All {len(successful)} profiles deleted successfully")
            return jsonify({
                "message": "All profiles deleted successfully",
                "deleted_count": len(successful),
                "results": {
                    "successful": successful,
                    "failed": []
                }
            }), 200
        elif len(successful) == 0:
            # All failed
            current_app.logger.warning(f"Bulk delete profiles: All {len(failed)} profiles failed to delete")
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
            current_app.logger.info(f"Bulk delete profiles: Partial success - {len(successful)} deleted, {len(failed)} failed")
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
        current_app.logger.exception(f"Bulk delete profiles: Unexpected error: {str(e)}")
        db.session.rollback()
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500


@bp.route('/<profile_id>', methods=['DELETE'])
@jwt_required()
def delete_profile(profile_id):
    """
    Delete a profile by ID.
    
    Requirements:
    - Profile must exist and belong to the requesting tenant
    - Profile must not be linked to any active campaigns
    - Email records will have their profile_id set to NULL if possible
    
    Returns:
    - 200: Profile deleted successfully
    - 400: Profile is linked to active campaigns
    - 403: Profile belongs to different tenant
    - 404: Profile not found
    - 500: Database error
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    
    if not tenant_id:
        current_app.logger.warning("Delete profile: Missing tenant_id in JWT token")
        return jsonify({"error": "Unauthorized"}), 401
    
    current_app.logger.debug(f"Delete profile: Request for profile_id={profile_id}, tenant_id={tenant_id}")
    
    try:
        # Verify profile exists
        profile = Profile.query.filter_by(profile_id=profile_id).first()
        
        if not profile:
            current_app.logger.warning(f"Delete profile: Profile not found profile_id={profile_id}, tenant_id={tenant_id}")
            return jsonify({"error": "Profile not found"}), 404
        
        # Verify profile belongs to requesting tenant
        if profile.tenant_id != tenant_id:
            current_app.logger.warning(
                f"Delete profile: Forbidden - profile belongs to different tenant. "
                f"profile_id={profile_id}, profile_tenant_id={profile.tenant_id}, requesting_tenant_id={tenant_id}"
            )
            return jsonify({"error": "Forbidden"}), 403
        
        current_app.logger.debug(
            f"Delete profile: Profile found profile_id={profile_id}, "
            f"person_name={profile.person_name}, tenant_id={tenant_id}"
        )
        
        # Check if profile is linked to any active campaigns
        active_campaign_profiles = CampaignProfile.query.filter_by(profile_id=profile_id).all()
        
        if active_campaign_profiles:
            campaign_ids = [cp.campaign_id for cp in active_campaign_profiles]
            current_app.logger.warning(
                f"Delete profile: Cannot delete - profile is linked to active campaigns. "
                f"profile_id={profile_id}, campaign_ids={campaign_ids}, tenant_id={tenant_id}"
            )
            return jsonify({
                "error": "Cannot delete profile: profile is linked to active campaigns"
            }), 400
        
        current_app.logger.debug(f"Delete profile: No active campaign links found for profile_id={profile_id}")
        
        # Check for emails linked to this profile
        emails_linked = Email.query.filter_by(profile_id=profile_id).count()
        
        if emails_linked > 0:
            current_app.logger.debug(
                f"Delete profile: Found {emails_linked} email(s) linked to profile_id={profile_id}. "
                f"Attempting to set profile_id to NULL"
            )
            
            # Try to set profile_id to NULL for linked emails
            # Note: This will only work if the foreign key constraint allows SET NULL
            # If it's RESTRICT, this will raise an IntegrityError which we'll catch
            try:
                Email.query.filter_by(profile_id=profile_id).update({Email.profile_id: None})
                db.session.flush()  # Flush to check for constraint violations
                current_app.logger.debug(
                    f"Delete profile: Successfully set profile_id to NULL for {emails_linked} email(s)"
                )
            except Exception as email_update_error:
                # If we can't set to NULL (e.g., RESTRICT constraint), prevent deletion
                current_app.logger.error(
                    f"Delete profile: Cannot set profile_id to NULL for emails. "
                    f"profile_id={profile_id}, error={str(email_update_error)}"
                )
                db.session.rollback()
                return jsonify({
                    "error": "Cannot delete profile: profile has associated emails that cannot be unlinked"
                }), 400
        
        # Delete the profile (CampaignProfile entries will be CASCADE deleted automatically)
        profile_person_name = profile.person_name
        profile_linkedin_url = profile.linkedin_url
        
        db.session.delete(profile)
        db.session.commit()
        
        current_app.logger.info(
            f"Delete profile: Successfully deleted profile. "
            f"profile_id={profile_id}, person_name={profile_person_name}, "
            f"linkedin_url={profile_linkedin_url}, tenant_id={tenant_id}, "
            f"emails_unlinked={emails_linked}"
        )
        
        return jsonify({"message": "Profile deleted successfully"}), 200
        
    except Exception as e:
        current_app.logger.exception(
            f"Delete profile: Error deleting profile_id={profile_id}, tenant_id={tenant_id}: {str(e)}"
        )
        db.session.rollback()
        return jsonify({
            "error": "Failed to delete profile",
            "details": str(e)
        }), 500