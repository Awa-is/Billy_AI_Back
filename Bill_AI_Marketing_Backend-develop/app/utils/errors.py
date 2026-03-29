"""
Error Response Utilities

Provides standardized error response formatting for all API endpoints.
All error responses follow the API specification format.
"""

from flask import jsonify, request
from marshmallow import ValidationError
import uuid


def validation_error_response(message, field=None, value=None, errors=None):
    """
    Create a standardized 400 Bad Request validation error response.
    
    Args:
        message (str): Human-readable error message
        field (str, optional): Field name that caused the error
        value (str, optional): Invalid value that was provided
        errors (dict, optional): Marshmallow validation errors dict
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "VALIDATION_ERROR",
            "message": "Invalid email address format",
            "details": {
                "field": "to",
                "value": "invalid-email"
            }
        }
    """
    response = {
        "error": "VALIDATION_ERROR",
        "message": message
    }
    
    # Add details if field/value provided
    if field or value or errors:
        details = {}
        if field:
            details["field"] = field
        if value:
            details["value"] = value
        if errors:
            # Merge marshmallow errors into details
            details.update(errors)
        response["details"] = details
    
    return jsonify(response), 400


def unauthorized_error_response(message="Authentication required"):
    """
    Create a standardized 401 Unauthorized error response.
    
    Args:
        message (str): Error message (default: "Authentication required")
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "UNAUTHORIZED",
            "message": "Authentication required"
        }
    """
    return jsonify({
        "error": "UNAUTHORIZED",
        "message": message
    }), 401


def forbidden_error_response(message="You don't have permission to access this resource"):
    """
    Create a standardized 403 Forbidden error response.
    
    Args:
        message (str): Error message
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "FORBIDDEN",
            "message": "You don't have permission to access this resource"
        }
    """
    return jsonify({
        "error": "FORBIDDEN",
        "message": message
    }), 403


def not_found_error_response(message="Resource not found", resource_type=None, resource_id=None):
    """
    Create a standardized 404 Not Found error response.
    
    Args:
        message (str): Error message
        resource_type (str, optional): Type of resource (e.g., "conversation", "Attachment", "Email")
        resource_id (str|int, optional): ID of the resource that was not found
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "NOT_FOUND",
            "message": "Conversation not found",
            "resourceType": "conversation",
            "resourceId": 999
        }
    """
    response = {
        "error": "NOT_FOUND",
        "message": message
    }
    
    # Add resourceType and resourceId at top level (not in details)
    if resource_type:
        response["resourceType"] = resource_type
    if resource_id is not None:
        response["resourceId"] = resource_id
    
    return jsonify(response), 404


def unprocessable_entity_error_response(message, **kwargs):
    """
    Create a standardized 422 Unprocessable Entity error response.
    
    Used when the request is well-formed but semantically incorrect
    (e.g., business logic validation fails).
    
    Args:
        message (str): Error message
        **kwargs: Additional fields to include (e.g., contactId=5)
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "UNPROCESSABLE_ENTITY",
            "message": "Cannot generate draft - contact has no signals",
            "contactId": 5
        }
    """
    response = {
        "error": "UNPROCESSABLE_ENTITY",
        "message": message
    }
    
    # Add any additional fields at top level
    response.update(kwargs)
    
    return jsonify(response), 422


def rate_limit_error_response(message="Too many requests. Please try again later.", retry_after=None):
    """
    Create a standardized 429 Too Many Requests error response.
    
    Args:
        message (str): Error message
        retry_after (int, optional): Seconds to wait before retrying
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "RATE_LIMITED",
            "message": "Too many requests. Please try again later.",
            "retryAfter": 60
        }
    """
    response = {
        "error": "RATE_LIMITED",
        "message": message
    }
    
    if retry_after is not None:
        response["retryAfter"] = retry_after
    
    return jsonify(response), 429


def internal_error_response(message="An unexpected error occurred", request_id=None):
    """
    Create a standardized 500 Internal Server Error response.
    
    Args:
        message (str): Error message
        request_id (str, optional): Request ID for tracking (auto-generated if not provided)
    
    Returns:
        tuple: (jsonify response, status_code)
    
    Example:
        {
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "requestId": "req_abc123"
        }
    """
    response = {
        "error": "INTERNAL_ERROR",
        "message": message
    }
    
    # Generate request ID if not provided
    if request_id is None:
        # Try to get from request context if available
        try:
            request_id = getattr(request, 'request_id', None)
        except RuntimeError:
            pass
        
        # Generate new ID if still None
        if request_id is None:
            request_id = f"req_{uuid.uuid4().hex[:8]}"
    
    response["requestId"] = request_id
    
    return jsonify(response), 500


def handle_validation_error(err):
    """
    Handle Marshmallow ValidationError and convert to standardized format.
    
    Args:
        err (ValidationError): Marshmallow validation error
    
    Returns:
        tuple: (jsonify response, status_code)
    """
    # Extract first error message for the main message
    first_field = None
    first_message = None
    first_value = None
    
    if err.messages:
        first_field = list(err.messages.keys())[0]
        first_message_list = err.messages[first_field]
        if first_message_list:
            first_message = first_message_list[0] if isinstance(first_message_list, list) else first_message_list
    
    message = first_message or "Validation failed"
    
    return validation_error_response(
        message=message,
        field=first_field,
        errors=err.messages
    )


def bad_request_error_response(message, error_code="BAD_REQUEST", details=None):
    """
    Create a standardized 400 Bad Request error response.
    
    Args:
        message (str): Error message
        error_code (str): Error code (default: "BAD_REQUEST")
        details (dict, optional): Additional details
    
    Returns:
        tuple: (jsonify response, status_code)
    """
    response = {
        "error": error_code,
        "message": message
    }
    
    if details:
        response["details"] = details
    
    return jsonify(response), 400
