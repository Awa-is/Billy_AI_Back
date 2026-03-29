"""
Attachment Handler Service

Handles processing attachment IDs and attaching files to emails.
"""

import logging
from typing import List, Optional, Dict, Any
from app.extensions import db
from app.models.attachment import Attachment

logger = logging.getLogger(__name__)


def process_attachment_ids(attachment_ids: Optional[List[str]], tenant_id: str) -> List[Dict[str, Any]]:
    """
    Process attachment IDs and return attachment file information.
    
    Args:
        attachment_ids: List of attachment IDs
        tenant_id: Tenant ID for validation
    
    Returns:
        List of dictionaries with attachment file information:
        [
            {
                "file_path": "/path/to/file.pdf",
                "filename": "proposal.pdf",
                "content_type": "application/pdf"
            },
            ...
        ]
    
    Raises:
        ValueError: If any attachment is not found or invalid
    """
    if not attachment_ids:
        return []
    
    attachments = []
    for attachment_id in attachment_ids:
        if not attachment_id or not attachment_id.strip():
            continue
        
        attachment = Attachment.query.filter_by(
            attachment_id=attachment_id.strip(),
            tenant_id=tenant_id,
            deleted_at=None
        ).first()
        
        if not attachment:
            raise ValueError(f"Attachment not found: {attachment_id}")
        
        # Check if attachment has expired (only if not permanent)
        if not attachment.is_permanent and attachment.expires_at:
            from datetime import datetime
            if datetime.utcnow() > attachment.expires_at:
                raise ValueError(f"Attachment has expired: {attachment_id}")
        
        attachments.append({
            "file_path": attachment.file_path,
            "filename": attachment.filename,
            "content_type": attachment.content_type
        })
    
    return attachments


def mark_attachments_as_permanent(attachment_ids: Optional[List[str]], tenant_id: str):
    """
    Mark attachments as permanent (linked to a sent email).
    This prevents them from expiring.
    
    Args:
        attachment_ids: List of attachment IDs to mark as permanent
        tenant_id: Tenant ID for validation
    """
    if not attachment_ids:
        return
    
    for attachment_id in attachment_ids:
        if not attachment_id or not attachment_id.strip():
            continue
        
        attachment = Attachment.query.filter_by(
            attachment_id=attachment_id.strip(),
            tenant_id=tenant_id,
            deleted_at=None
        ).first()
        
        if attachment:
            attachment.is_permanent = True
            attachment.expires_at = None  # Remove expiration for permanent attachments
            logger.info(f"Marked attachment {attachment_id} as permanent")
    
    db.session.commit()


def store_attachment_ids_in_email(email, attachment_ids: Optional[List[str]]):
    """
    Store attachment IDs in email record.
    
    Args:
        email: Email model instance
        attachment_ids: List of attachment IDs (can be None or empty)
    """
    if attachment_ids:
        # Store as comma-separated string
        email.attachment_ids = ','.join(attachment_ids)
    else:
        email.attachment_ids = None
