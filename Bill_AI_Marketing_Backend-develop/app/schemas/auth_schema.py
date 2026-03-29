from marshmallow import Schema, fields, validates, ValidationError
import re

class RegisterSchema(Schema):
    """
    Registration Request Validation Schema
    
    Validates user registration input:
    - Email must be valid format
    - Password must be strong (min 8 chars, 1 uppercase, 1 number)
    - All fields required
    
    Example:
        schema = RegisterSchema()
        result = schema.load(request_data)
    """
    email = fields.Email(required=True, error_messages={
        "required": "Email is required",
        "invalid": "Invalid email format"
    })
    
    password = fields.Str(required=True, error_messages={
        "required": "Password is required"
    })
    
    first_name = fields.Str(required=True, error_messages={
        "required": "First name is required"
    })
    
    last_name = fields.Str(required=True, error_messages={
        "required": "Last name is required"
    })
    
    company_name = fields.Str(required=True, error_messages={
        "required": "Company/workspace name is required"
    })
    
    @validates('password')
    def validate_password(self, value):
        """
        Validate password strength
        
        Requirements:
        - Minimum 8 characters
        - At least 1 uppercase letter
        - At least 1 number
        
        Raises:
            ValidationError: If password doesn't meet requirements
        """
        if len(value) < 8:
            raise ValidationError("Password must be at least 8 characters long")
        
        if not re.search(r'[A-Z]', value):
            raise ValidationError("Password must contain at least one uppercase letter")
        
        if not re.search(r'\d', value):
            raise ValidationError("Password must contain at least one number")
    
    @validates('company_name')
    def validate_company_name(self, value):
        """
        Validate company/workspace name
        
        Requirements:
        - Minimum 2 characters
        - Maximum 255 characters
        """
        if len(value) < 2:
            raise ValidationError("Company name must be at least 2 characters")
        
        if len(value) > 255:
            raise ValidationError("Company name must be less than 255 characters")


class UserResponseSchema(Schema):
    """
    User Response Schema
    
    Defines what user data is returned to frontend.
    Never return password_hash or sensitive data!
    """
    user_id = fields.Str()
    email = fields.Email()
    first_name = fields.Str()
    last_name = fields.Str()
    role = fields.Str()
    tenant_id = fields.Str()
    created_at = fields.DateTime()


class TenantResponseSchema(Schema):
    """
    Tenant Response Schema
    
    Defines what tenant data is returned.
    """
    tenant_id = fields.Str()
    company_name = fields.Str()
    plan = fields.Str()
    status = fields.Str()