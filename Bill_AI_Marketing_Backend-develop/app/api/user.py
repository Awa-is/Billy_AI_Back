"""
User API Endpoints

Endpoints for user-specific operations like AI instructions.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, ValidationError, validates
from app.extensions import db
from app.models.user_setting import UserSetting
from app.models.user import User
from datetime import datetime
import json

bp = Blueprint('user', __name__)


# Schema for adding a new instruction
class AddInstructionSchema(Schema):
    text = fields.Str(required=True, validate=lambda x: len(x.strip()) > 0, error_messages={"required": "Text is required"})
    
    @validates('text')
    def validate_text(self, value):
        if not value or not value.strip():
            raise ValidationError("Text cannot be empty")
        if len(value.strip()) > 5000:
            raise ValidationError("Text must be max 5000 characters")


add_instruction_schema = AddInstructionSchema()


@bp.route('/ai-instructions', methods=['GET'])
@jwt_required()
def get_ai_instructions():
    """
    Get user-specific AI instructions.
    
    Retrieves user's AI email generation instructions/preferences.
    Used In UI: AIInstructionsPanel.tsx - Settings/preferences panel
    When Called: When user opens AI preferences modal, and also fetched when generating emails to include in AI prompts
    UI Elements: List of instruction cards with text, edit/delete buttons for each instruction
    
    Returns:
        200 OK with instructions array (if set)
        200 OK with empty array if instructions not set (instead of 404)
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Get user's AI instructions
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    if not user_setting or not user_setting.value:
        # Return empty array instead of 404 for better UX
        return jsonify({
            "instructions": []
        }), 200
    
    # Parse instructions - support both JSON array and plain text
    instructions_value = user_setting.value
    instructions_list = []
    
    try:
        # Try to parse as JSON array
        parsed = json.loads(instructions_value)
        if isinstance(parsed, list):
            instructions_list = parsed
        else:
            # If it's a single value, convert to array
            instructions_list = [parsed] if parsed else []
    except (json.JSONDecodeError, TypeError):
        # If not JSON, treat as plain text
        # Split by newlines and filter empty lines
        if instructions_value:
            instructions_list = [
                {"id": i, "text": line.strip()}
                for i, line in enumerate(instructions_value.split('\n'))
                if line.strip()
            ]
    
    # Ensure all items have id, text, and createdAt structure
    formatted_instructions = []
    # Use UserSetting.created_at as default, or individual createdAt if stored in JSON
    default_created_at = user_setting.created_at.isoformat() if user_setting.created_at else None
    
    for idx, item in enumerate(instructions_list):
        if isinstance(item, dict):
            # If already a dict, ensure it has id, text, and createdAt
            instruction_id = item.get("id", idx)
            instruction_text = item.get("text", str(item)).strip()
            instruction_created_at = item.get("createdAt")
            
            # If createdAt is a string, use it; if datetime, convert to ISO; otherwise use default
            if instruction_created_at:
                if hasattr(instruction_created_at, 'isoformat'):
                    instruction_created_at = instruction_created_at.isoformat()
                elif isinstance(instruction_created_at, str):
                    pass  # Already a string
                else:
                    instruction_created_at = default_created_at
            else:
                instruction_created_at = default_created_at
            
            formatted_instructions.append({
                "id": instruction_id,
                "text": instruction_text,
                "createdAt": instruction_created_at
            })
        else:
            # If it's a string, convert to dict
            formatted_instructions.append({
                "id": idx,
                "text": str(item).strip(),
                "createdAt": default_created_at
            })
    
    return jsonify({
        "instructions": formatted_instructions
    }), 200


@bp.route('/ai-instructions', methods=['POST'])
@jwt_required()
def add_ai_instruction():
    """
    Add a new AI instruction.
    
    Adds a new instruction to the user's AI email generation preferences.
    Used In UI: AIInstructionsPanel.tsx
    When Called: When user types a new instruction and clicks "Add" button
    UI Elements: Text input field with "Add" button, new instruction appears in list after success
    
    Request Body:
        {
            "text": "Always mention our Q4 promotion"
        }
    
    Returns:
        201 CREATED with the new instruction object
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Validate request body
    data = request.get_json() or {}
    try:
        validated = add_instruction_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    instruction_text = validated['text'].strip()
    
    # Get existing instructions or create new setting
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    # Parse existing instructions
    existing_instructions = []
    if user_setting and user_setting.value:
        try:
            parsed = json.loads(user_setting.value)
            if isinstance(parsed, list):
                existing_instructions = parsed
            else:
                existing_instructions = [parsed] if parsed else []
        except (json.JSONDecodeError, TypeError):
            # If not JSON, treat as plain text
            if user_setting.value:
                existing_instructions = [
                    {"id": i, "text": line.strip()}
                    for i, line in enumerate(user_setting.value.split('\n'))
                    if line.strip()
                ]
    
    # Generate new ID (next available ID)
    if existing_instructions:
        # Get the maximum ID from existing instructions
        max_id = max(
            (inst.get("id", idx) for idx, inst in enumerate(existing_instructions) if isinstance(inst, dict)),
            default=-1
        )
        new_id = max_id + 1
    else:
        new_id = 0
    
    # Create new instruction object
    new_instruction = {
        "id": new_id,
        "text": instruction_text,
        "createdAt": datetime.utcnow().isoformat()
    }
    
    # Add to existing instructions
    existing_instructions.append(new_instruction)
    
    # Save to database
    if user_setting:
        # Update existing setting
        user_setting.value = json.dumps(existing_instructions)
    else:
        # Create new setting
        user_setting = UserSetting(
            user_id=current_user_id,
            key='ai_email_instructions',
            value=json.dumps(existing_instructions)
        )
        db.session.add(user_setting)
    
    db.session.commit()
    
    # Return the new instruction
    return jsonify(new_instruction), 201


@bp.route('/ai-instructions/<int:instruction_id>', methods=['PUT'])
@jwt_required()
def update_ai_instruction(instruction_id):
    """
    Update an existing AI instruction.
    
    Updates an existing instruction in the user's AI email generation preferences.
    Used In UI: AIInstructionsPanel.tsx
    When Called: When user clicks edit icon on an instruction, modifies text, and saves
    UI Elements: Edit icon on instruction card, inline text editing, save/cancel buttons
    
    URL Parameters:
        instruction_id (int): The ID of the instruction to update
    
    Request Body:
        {
            "text": "Always mention our Q1 2026 promotion"
        }
    
    Returns:
        200 OK with the updated instruction object (id, text, updatedAt)
        404 NOT FOUND if instruction doesn't exist
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Validate request body
    data = request.get_json() or {}
    try:
        validated = add_instruction_schema.load(data)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400
    
    new_text = validated['text'].strip()
    
    # Get existing instructions
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    if not user_setting or not user_setting.value:
        return jsonify({"error": "No instructions found"}), 404
    
    # Parse existing instructions
    existing_instructions = []
    try:
        parsed = json.loads(user_setting.value)
        if isinstance(parsed, list):
            existing_instructions = parsed
        else:
            existing_instructions = [parsed] if parsed else []
    except (json.JSONDecodeError, TypeError):
        # If not JSON, treat as plain text
        if user_setting.value:
            existing_instructions = [
                {"id": i, "text": line.strip()}
                for i, line in enumerate(user_setting.value.split('\n'))
                if line.strip()
            ]
    
    # Find the instruction with matching ID
    instruction_found = False
    for idx, inst in enumerate(existing_instructions):
        if isinstance(inst, dict):
            inst_id = inst.get("id", idx)
            if inst_id == instruction_id:
                # Update the instruction
                existing_instructions[idx]["text"] = new_text
                existing_instructions[idx]["updatedAt"] = datetime.utcnow().isoformat()
                # Preserve createdAt if it exists
                if "createdAt" not in existing_instructions[idx]:
                    # Use default createdAt if not present
                    default_created_at = user_setting.created_at.isoformat() if user_setting.created_at else None
                    if default_created_at:
                        existing_instructions[idx]["createdAt"] = default_created_at
                instruction_found = True
                break
        elif idx == instruction_id:
            # Handle case where instruction is a string and index matches ID
            # Preserve createdAt from user_setting if available
            default_created_at = user_setting.created_at.isoformat() if user_setting.created_at else None
            existing_instructions[idx] = {
                "id": instruction_id,
                "text": new_text,
                "updatedAt": datetime.utcnow().isoformat()
            }
            if default_created_at:
                existing_instructions[idx]["createdAt"] = default_created_at
            instruction_found = True
            break
    
    if not instruction_found:
        return jsonify({"error": "Instruction not found"}), 404
    
    # Save updated instructions to database
    user_setting.value = json.dumps(existing_instructions)
    db.session.commit()
    
    # Get the updated instruction for response
    updated_instruction = None
    for inst in existing_instructions:
        if isinstance(inst, dict) and inst.get("id") == instruction_id:
            updated_instruction = {
                "id": inst.get("id"),
                "text": inst.get("text"),
                "updatedAt": inst.get("updatedAt")
            }
            break
    
    if not updated_instruction:
        return jsonify({"error": "Failed to retrieve updated instruction"}), 500
    
    # Return the updated instruction
    return jsonify(updated_instruction), 200


@bp.route('/ai-instructions/<int:instruction_id>', methods=['DELETE'])
@jwt_required()
def delete_ai_instruction(instruction_id):
    """
    Delete an AI instruction.
    
    Deletes an existing instruction from the user's AI email generation preferences.
    Used In UI: AIInstructionsPanel.tsx
    When Called: When user clicks trash/delete icon on an instruction
    UI Elements: Delete icon on instruction card, confirmation optional, instruction removed from list
    
    URL Parameters:
        instruction_id (int): The ID of the instruction to delete
    
    Returns:
        204 NO CONTENT if instruction was deleted successfully
        404 NOT FOUND if instruction doesn't exist
    """
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    current_user_id = get_jwt_identity()
    
    # Get existing instructions
    user_setting = UserSetting.query.filter_by(
        user_id=current_user_id,
        key='ai_email_instructions'
    ).first()
    
    if not user_setting or not user_setting.value:
        return jsonify({"error": "No instructions found"}), 404
    
    # Parse existing instructions
    existing_instructions = []
    try:
        parsed = json.loads(user_setting.value)
        if isinstance(parsed, list):
            existing_instructions = parsed
        else:
            existing_instructions = [parsed] if parsed else []
    except (json.JSONDecodeError, TypeError):
        # If not JSON, treat as plain text
        if user_setting.value:
            existing_instructions = [
                {"id": i, "text": line.strip()}
                for i, line in enumerate(user_setting.value.split('\n'))
                if line.strip()
            ]
    
    # Find and remove the instruction with matching ID
    instruction_found = False
    updated_instructions = []
    for idx, inst in enumerate(existing_instructions):
        if isinstance(inst, dict):
            inst_id = inst.get("id", idx)
            if inst_id != instruction_id:
                # Keep instructions that don't match the ID
                updated_instructions.append(inst)
            else:
                # Found the instruction to delete
                instruction_found = True
        elif idx != instruction_id:
            # Keep instructions that don't match the index
            updated_instructions.append(inst)
        else:
            # Found the instruction to delete (by index)
            instruction_found = True
    
    if not instruction_found:
        return jsonify({"error": "Instruction not found"}), 404
    
    # Save updated instructions to database
    if updated_instructions:
        user_setting.value = json.dumps(updated_instructions)
    else:
        # If no instructions left, we can either delete the setting or keep it empty
        # Keeping it as empty array for consistency
        user_setting.value = json.dumps([])
    
    db.session.commit()
    
    # Return 204 NO CONTENT (no response body)
    return '', 204
