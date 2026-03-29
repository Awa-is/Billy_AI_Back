from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from marshmallow import Schema, fields, validates, ValidationError
from app.extensions import db
from app.models.email_template import EmailTemplate
import re
from datetime import datetime

bp = Blueprint('templates', __name__)

# Allowed template variables
ALLOWED_VARIABLES = {
    'recipient_name',
    'company_name',
    'product_name',
    'sender_name',
    'post_summary'
}


def validate_template_variables(text):
    """
    Validate that all {{variables}} in text are from the allowed list.
    
    Returns:
        tuple: (is_valid, invalid_vars_list)
    """
    if not text:
        return True, []
    
    # Find all {{variable}} patterns
    pattern = r'\{\{(\w+)\}\}'
    matches = re.findall(pattern, text)
    
    invalid_vars = []
    for var in matches:
        if var not in ALLOWED_VARIABLES:
            invalid_vars.append(var)
    
    return len(invalid_vars) == 0, invalid_vars


def extract_variables(text):
    """Extract all variable names from template text."""
    if not text:
        return []
    pattern = r'\{\{(\w+)\}\}'
    matches = re.findall(pattern, text)
    return list(set(matches))  # Return unique variables


def render_template(text, variables):
    """Replace {{variable}} placeholders with actual values."""
    if not text:
        return text
    
    result = text
    for var_name, var_value in variables.items():
        placeholder = f'{{{{{var_name}}}}}'
        result = result.replace(placeholder, str(var_value))
    
    return result


class CreateTemplateSchema(Schema):
    name = fields.Str(required=True, error_messages={"required": "Name is required"})
    subject = fields.Str(required=True, error_messages={"required": "Subject is required"})
    body = fields.Str(required=True, error_messages={"required": "Body is required"})
    
    @validates('name')
    def validate_name(self, value):
        if not value or not value.strip():
            raise ValidationError("Name cannot be empty")
        if len(value) > 100:
            raise ValidationError("Name must be less than 100 characters")
    
    @validates('subject')
    def validate_subject(self, value):
        if not value or not value.strip():
            raise ValidationError("Subject cannot be empty")
        if len(value) > 200:
            raise ValidationError("Subject must be less than 200 characters")
    
    @validates('body')
    def validate_body(self, value):
        if not value or not value.strip():
            raise ValidationError("Body cannot be empty")
        if len(value) > 5000:
            raise ValidationError("Body must be less than 5000 characters")
    
    def validate_template_variables(self, data):
        """Custom validation for template variables."""
        subject = data.get('subject', '')
        body = data.get('body', '')
        
        # Check subject
        is_valid, invalid_vars = validate_template_variables(subject)
        if not is_valid:
            raise ValidationError(f"Variable {{{{{invalid_vars[0]}}}}} not allowed in subject")
        
        # Check body
        is_valid, invalid_vars = validate_template_variables(body)
        if not is_valid:
            raise ValidationError(f"Variable {{{{{invalid_vars[0]}}}}} not allowed in body")


class UpdateTemplateSchema(Schema):
    name = fields.Str(required=False)
    subject = fields.Str(required=False)
    body = fields.Str(required=False)
    
    @validates('name')
    def validate_name(self, value):
        if value is None:
            return
        if not value.strip():
            raise ValidationError("Name cannot be empty")
        if len(value) > 100:
            raise ValidationError("Name must be less than 100 characters")
    
    @validates('subject')
    def validate_subject(self, value):
        if value is None:
            return
        if not value.strip():
            raise ValidationError("Subject cannot be empty")
        if len(value) > 200:
            raise ValidationError("Subject must be less than 200 characters")
    
    @validates('body')
    def validate_body(self, value):
        if value is None:
            return
        if not value.strip():
            raise ValidationError("Body cannot be empty")
        if len(value) > 5000:
            raise ValidationError("Body must be less than 5000 characters")


class PreviewTemplateSchema(Schema):
    recipient_name = fields.Str(required=False, load_default="John Doe")
    company_name = fields.Str(required=False, load_default="Acme Inc")
    product_name = fields.Str(required=False, load_default="New Product")
    sender_name = fields.Str(required=False, load_default="Jane Smith")
    post_summary = fields.Str(required=False, load_default="This is a sample post summary.")


create_template_schema = CreateTemplateSchema()
update_template_schema = UpdateTemplateSchema()
preview_template_schema = PreviewTemplateSchema()


def template_to_dict(template):
    """Convert EmailTemplate model to dictionary."""
    all_text = f"{template.subject} {template.body}"
    variables = extract_variables(all_text)
    
    return {
        "template_id": template.template_id,
        "name": template.name,
        "subject": template.subject,
        "body": template.body,
        "is_default": template.is_default,
        "variables": variables,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None
    }


@bp.route('', methods=['GET'])
@jwt_required()
def list_templates():
    """
    List all templates for the current tenant.
    
    Returns:
        - Default templates (is_default=True, tenant_id=NULL)
        - Custom templates for the current tenant (is_default=False, tenant_id=current_tenant)
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get default templates (tenant_id is NULL)
    default_templates = EmailTemplate.query.filter(
        EmailTemplate.is_default == True,
        EmailTemplate.tenant_id.is_(None)
    ).all()
    
    # Get custom templates for this tenant
    custom_templates = EmailTemplate.query.filter(
        EmailTemplate.tenant_id == tenant_id,
        EmailTemplate.is_default == False
    ).all()
    
    # Combine and format
    all_templates = list(default_templates) + list(custom_templates)
    templates = [template_to_dict(t) for t in all_templates]
    
    return jsonify({"templates": templates}), 200


@bp.route('', methods=['POST'])
@jwt_required()
def create_template():
    """
    Create a custom email template for the current tenant.
    
    Request Body:
        {
            "name": "My Custom Template",
            "subject": "Hello {{recipient_name}}",
            "body": "Hi {{recipient_name}}, ..."
        }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    
    try:
        validated = create_template_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    # Validate template variables
    subject = validated['subject']
    body = validated['body']
    
    is_valid, invalid_vars = validate_template_variables(subject)
    if not is_valid:
        return jsonify({"error": f"Variable {{{{{invalid_vars[0]}}}}} not allowed"}), 400
    
    is_valid, invalid_vars = validate_template_variables(body)
    if not is_valid:
        return jsonify({"error": f"Variable {{{{{invalid_vars[0]}}}}} not allowed"}), 400
    
    # Create template
    template = EmailTemplate(
        tenant_id=tenant_id,
        name=validated['name'].strip(),
        subject=validated['subject'].strip(),
        body=validated['body'].strip(),
        is_default=False
    )
    
    db.session.add(template)
    db.session.commit()
    
    return jsonify({"template": template_to_dict(template)}), 201


@bp.route('/<template_id>', methods=['GET'])
@jwt_required()
def get_template(template_id):
    """
    Get a single template by ID.
    
    Returns:
        - Default templates (visible to all tenants)
        - Custom templates (only if owned by current tenant)
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    template = EmailTemplate.query.filter_by(template_id=template_id).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Check access: default templates are visible to all, custom templates only to owner
    if not template.is_default and template.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    return jsonify({"template": template_to_dict(template)}), 200


@bp.route('/<template_id>', methods=['PATCH'])
@jwt_required()
def update_template(template_id):
    """
    Update a custom template.
    
    Cannot update default templates (only custom templates).
    
    Request Body (all fields optional):
        {
            "name": "Updated Name",
            "subject": "Updated {{subject}}",
            "body": "Updated body..."
        }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    template = EmailTemplate.query.filter_by(template_id=template_id).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Cannot update default templates
    if template.is_default:
        return jsonify({"error": "Cannot update default templates"}), 400
    
    # Check ownership
    if template.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    
    try:
        validated = update_template_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    # Validate template variables if subject or body are being updated
    if 'subject' in validated:
        is_valid, invalid_vars = validate_template_variables(validated['subject'])
        if not is_valid:
            return jsonify({"error": f"Variable {{{{{invalid_vars[0]}}}}} not allowed"}), 400
    
    if 'body' in validated:
        is_valid, invalid_vars = validate_template_variables(validated['body'])
        if not is_valid:
            return jsonify({"error": f"Variable {{{{{invalid_vars[0]}}}}} not allowed"}), 400
    
    # Update fields
    if 'name' in validated:
        template.name = validated['name'].strip()
    if 'subject' in validated:
        template.subject = validated['subject'].strip()
    if 'body' in validated:
        template.body = validated['body'].strip()
    
    template.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({"template": template_to_dict(template)}), 200


@bp.route('/<template_id>', methods=['DELETE'])
@jwt_required()
def delete_template(template_id):
    """
    Delete a custom template.
    
    Cannot delete default templates.
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    template = EmailTemplate.query.filter_by(template_id=template_id).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Cannot delete default templates
    if template.is_default:
        return jsonify({"error": "Cannot delete default templates"}), 400
    
    # Check ownership
    if template.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    db.session.delete(template)
    db.session.commit()
    
    return jsonify({"message": "Template deleted successfully"}), 200


@bp.route('/<template_id>/preview', methods=['POST'])
@jwt_required()
def preview_template(template_id):
    """
    Preview a template with sample data.
    
    Request Body (all fields optional, defaults provided):
        {
            "recipient_name": "John Doe",
            "company_name": "Acme Inc",
            "product_name": "New Product",
            "sender_name": "Jane Smith",
            "post_summary": "Sample post summary..."
        }
    
    Returns:
        {
            "subject": "Rendered subject",
            "body": "Rendered body"
        }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    template = EmailTemplate.query.filter_by(template_id=template_id).first()
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Check access: default templates are visible to all, custom templates only to owner
    if not template.is_default and template.tenant_id != tenant_id:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    
    try:
        validated = preview_template_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    # Render template with provided values
    rendered_subject = render_template(template.subject, validated)
    rendered_body = render_template(template.body, validated)
    
    return jsonify({
        "subject": rendered_subject,
        "body": rendered_body
    }), 200

