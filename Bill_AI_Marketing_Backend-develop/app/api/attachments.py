"""
Attachments API Endpoints

Handles file upload, retrieval, and deletion for email attachments.
Follows a two-step process:
1. Upload file → Get attachment ID
2. Reference ID when sending email
"""

from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.attachment import Attachment
from app.models.user import User
from datetime import datetime, timedelta
from sqlalchemy import or_
import os
import uuid

bp = Blueprint('attachments', __name__)


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in [e.lower() for e in allowed_extensions]


def get_upload_folder():
    """Get the upload folder path, creating it if it doesn't exist."""
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


@bp.route('', methods=['GET'])
@jwt_required()
def list_attachments():
    """
    List user's uploaded attachments that haven't been sent yet.
    Useful for cleanup.
    
    Used In UI: Optional - could be used in settings or attachment manager
    When Called: Optional endpoint for admin/cleanup purposes
    UI Elements: Could show pending attachments that will expire soon
    
    Query Parameters:
        status (string, optional): Filter by status ('pending', 'permanent', 'expired', 'all')
        limit (int, optional): Maximum number of results (default: 50)
        offset (int, optional): Number of results to skip (default: 0)
    
    Returns:
        200 OK with list of pending attachments
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Get query parameters
    status_filter = request.args.get('status', 'pending')  # Default to 'pending'
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    # Build query for attachments
    query = Attachment.query.filter(
        Attachment.tenant_id == tenant_id,
        Attachment.user_id == current_user_id,
        Attachment.deleted_at.is_(None)
    )
    
    # Apply status filter
    if status_filter == 'pending':
        # Pending: not permanent and not expired
        query = query.filter(
            Attachment.is_permanent == False,
            or_(
                Attachment.expires_at.is_(None),
                Attachment.expires_at > datetime.utcnow()
            )
        )
    elif status_filter == 'permanent':
        # Permanent: attached to sent emails
        query = query.filter(Attachment.is_permanent == True)
    elif status_filter == 'expired':
        # Expired: not permanent and past expiration date
        query = query.filter(
            Attachment.is_permanent == False,
            Attachment.expires_at.isnot(None),
            Attachment.expires_at <= datetime.utcnow()
        )
    # If status is 'all' or invalid, show all non-deleted attachments
    
    # Order by creation date (newest first)
    query = query.order_by(Attachment.created_at.desc())
    
    # Apply pagination
    total = query.count()
    attachments = query.limit(limit).offset(offset).all()
    
    # Format response
    attachments_list = []
    for attachment in attachments:
        # Determine status
        if attachment.is_permanent:
            status = "permanent"
        elif attachment.expires_at and attachment.expires_at <= datetime.utcnow():
            status = "expired"
        else:
            status = "pending"
        
        attachments_list.append({
            "id": attachment.attachment_id,
            "filename": attachment.filename,
            "size": attachment.file_size,
            "mimeType": attachment.content_type,
            "uploadedAt": attachment.created_at.isoformat() if attachment.created_at else None,
            "expiresAt": attachment.expires_at.isoformat() if attachment.expires_at else None,
            "status": status
        })
    
    return jsonify({
        "attachments": attachments_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }), 200


@bp.route('', methods=['POST'])
@jwt_required()
def upload_attachment():
    """
    Upload a file attachment.
    
    Used In UI: ComposeView.tsx - When user clicks "Attach" button
    When Called: When user selects a file to attach to an email
    UI Elements: File input, upload progress indicator
    
    Request:
        Content-Type: multipart/form-data
        Body: { file: [binary data] }
    
    Returns:
        201 CREATED with attachment ID and filename
        400 BAD REQUEST if file is invalid or too large
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Check if file is present
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    # Check if file was actually selected
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    # Validate file extension
    allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', set())
    if not allowed_file(file.filename, allowed_extensions):
        return jsonify({
            "error": "File type not allowed",
            "allowedTypes": list(allowed_extensions)
        }), 400
    
    # Validate file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset file pointer
    
    max_file_size = current_app.config.get('MAX_FILE_SIZE', 10 * 1024 * 1024)
    if file_size > max_file_size:
        return jsonify({
            "error": "File too large",
            "maxSize": max_file_size,
            "fileSize": file_size
        }), 400
    
    # Generate secure filename and unique file path
    original_filename = secure_filename(file.filename)
    file_extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    unique_filename = f"{uuid.uuid4()}.{file_extension}" if file_extension else str(uuid.uuid4())
    
    # Get upload folder and save file
    upload_folder = get_upload_folder()
    file_path = os.path.join(upload_folder, unique_filename)
    
    try:
        file.save(file_path)
    except Exception as e:
        current_app.logger.error(f"Error saving file: {e}")
        return jsonify({"error": "Failed to save file"}), 500
    
    # Get content type
    content_type = file.content_type or 'application/octet-stream'
    
    # Calculate expiration time (24 hours from now if not attached to email)
    expiry_hours = current_app.config.get('ATTACHMENT_EXPIRY_HOURS', 24)
    expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
    
    # Create attachment record
    attachment = Attachment(
        tenant_id=tenant_id,
        user_id=current_user_id,
        filename=original_filename,
        file_path=file_path,
        file_size=file_size,
        content_type=content_type,
        expires_at=expires_at,
        is_permanent=False  # Will become permanent when attached to sent email
    )
    
    db.session.add(attachment)
    db.session.commit()
    
    # Return response matching API spec
    return jsonify({
        "id": attachment.attachment_id,
        "filename": attachment.filename,
        "size": attachment.file_size,
        "mimeType": attachment.content_type,
        "uploadedAt": attachment.created_at.isoformat() if attachment.created_at else None,
        "expiresAt": attachment.expires_at.isoformat() if attachment.expires_at else None
    }), 201


@bp.route('/<attachment_id>', methods=['GET'])
@jwt_required()
def get_attachment(attachment_id):
    """
    Download an attachment file.
    
    Used In UI: EmailDetailView.tsx (sent email view)
    When Called: When user clicks on an attachment in a sent email to download it
    UI Elements: Attachment chip/link in email detail, triggers browser file download
    
    URL Parameters:
        attachment_id (string): The ID of the attachment
    
    Response Headers:
        Content-Type: application/pdf (or appropriate MIME type)
        Content-Disposition: attachment; filename="proposal.pdf"
        Content-Length: 245000 (file size in bytes)
    
    Response Body:
        Binary file stream
    
    Returns:
        200 OK with binary file content
        404 NOT FOUND if attachment doesn't exist
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get attachment
    attachment = Attachment.query.filter_by(
        attachment_id=attachment_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not attachment:
        return jsonify({"error": "Attachment not found"}), 404
    
    # Check if file exists on disk
    if not os.path.exists(attachment.file_path):
        return jsonify({"error": "File not found on server"}), 404
    
    # Send file with proper headers
    # Flask's send_file automatically sets:
    # - Content-Type from mimetype parameter
    # - Content-Disposition: attachment; filename="..." from download_name
    # - Content-Length from file size
    return send_file(
        attachment.file_path,
        as_attachment=True,
        download_name=attachment.filename,
        mimetype=attachment.content_type
    )


@bp.route('/<attachment_id>', methods=['DELETE'])
@jwt_required()
def delete_attachment(attachment_id):
    """
    Delete an uploaded attachment. Only works for attachments not yet sent.
    
    Used In UI: ComposeView.tsx + EmailDetailView.tsx (draft mode)
    When Called: When user clicks X button on an attachment chip to remove it before sending
    UI Elements: X icon on attachment chip, removes attachment from compose view
    
    URL Parameters:
        attachment_id (string): The ID of the attachment to delete
    
    Returns:
        204 NO CONTENT if deleted successfully
        404 NOT FOUND if attachment doesn't exist
        400 BAD REQUEST if attachment is already used in sent email
    
    Error Response (if already sent):
    {
        "error": "ATTACHMENT_IN_USE",
        "message": "Cannot delete attachment - already sent with email",
        "emailId": 123
    }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Get attachment
    attachment = Attachment.query.filter_by(
        attachment_id=attachment_id,
        tenant_id=tenant_id,
        deleted_at=None
    ).first()
    
    if not attachment:
        return jsonify({"error": "Attachment not found"}), 404
    
    # Check if attachment is linked to any sent emails
    # This prevents deletion of attachments that have been sent
    from app.models.email import Email
    from sqlalchemy import or_, and_
    
    # Search for emails that contain this attachment ID in the comma-separated attachment_ids field
    # We need to check for exact match in the comma-separated list
    # Pattern: attachment_id at start, middle (preceded by comma), or end (followed by comma)
    # Also check if email has been sent (status='sent' OR sent_at is not null)
    emails_using_attachment = Email.query.filter(
        Email.tenant_id == tenant_id,
        Email.deleted_at.is_(None),
        or_(
            Email.status == 'sent',
            Email.sent_at.isnot(None)  # Email has been sent (even if status not updated yet)
        ),
        or_(
            Email.attachment_ids == attachment_id,  # Only attachment
            Email.attachment_ids.like(f'{attachment_id},%'),  # First in list
            Email.attachment_ids.like(f'%,{attachment_id},%'),  # Middle of list
            Email.attachment_ids.like(f'%,{attachment_id}')  # End of list
        )
    ).all()
    
    if emails_using_attachment:
        # Return error with first email ID that uses it
        email_id = emails_using_attachment[0].email_id
        return jsonify({
            "error": "ATTACHMENT_IN_USE",
            "message": "Cannot delete attachment - already sent with email",
            "emailId": email_id
        }), 400
    
    # Soft delete (set deleted_at timestamp)
    attachment.deleted_at = datetime.utcnow()
    db.session.commit()
    
    # Optionally delete file from disk (or keep for audit)
    # For now, we'll keep the file but mark as deleted in DB
    # Uncomment below if you want to delete the file immediately:
    # try:
    #     if os.path.exists(attachment.file_path):
    #         os.remove(attachment.file_path)
    # except Exception as e:
    #     current_app.logger.error(f"Error deleting file: {e}")
    
    # Return 204 NO CONTENT
    return '', 204
