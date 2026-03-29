import json
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, validates, ValidationError
from app.extensions import db
from app.models.user_setting import UserSetting
from app.models.user import User

bp = Blueprint('aiinstructions', __name__)


class AIInstructionListSchema(Schema):
    instructions = fields.List(fields.Str(), required=True)
    
    @validates('instructions')
    def validate_instructions(self, value):
        if len(value) > 20:
             raise ValidationError("Maximum 20 instructions allowed")
        for item in value:
            if len(item) > 1000:
                raise ValidationError("Instruction length must be max 1000 characters")


ai_instruction_list_schema = AIInstructionListSchema()


@bp.route('', methods=['PUT'])
@jwt_required()
def update_ai_instructions():
    """
    Update/Replace all AI instructions.
    
    Request Body:
        {
            "instructions": ["Make it short", "Use friendly tone"]
        }
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    data = request.get_json() or {}
    
    try:
        validated = ai_instruction_list_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    instructions_list = validated['instructions']
    
    # Check if setting exists
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    json_value = json.dumps(instructions_list)
    
    if user_setting:
        user_setting.value = json_value
    else:
        user_setting = UserSetting(
            user_id=current_user_id,
            key='ai_email_instructions',
            value=json_value
        )
        db.session.add(user_setting)
    
    db.session.commit()
    
    # Return formatted list
    formatted = [{"id": i, "text": text} for i, text in enumerate(instructions_list)]
    
    return jsonify({
        "message": "AI instructions updated successfully",
        "instructions": formatted
    }), 200


@bp.route('', methods=['GET'])
@jwt_required()
def get_ai_instructions():
    """
    Get user-specific AI instructions.
    """
    claims = get_jwt()
    if not claims.get('tenant_id'):
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    if not user_setting or not user_setting.value:
        return jsonify({"instructions": []}), 200
    
    try:
        # Try parse JSON
        instructions_list = json.loads(user_setting.value)
        if not isinstance(instructions_list, list):
            instructions_list = [str(instructions_list)]
    except:
        # Fallback to newline split
        instructions_list = [line for line in user_setting.value.split('\n') if line.strip()]

    formatted = []
    for idx, item in enumerate(instructions_list):
        if isinstance(item, dict):
             formatted.append({"id": idx, "text": item.get("text", "")})
        else:
             formatted.append({"id": idx, "text": str(item)})
             
    return jsonify({"instructions": formatted}), 200


