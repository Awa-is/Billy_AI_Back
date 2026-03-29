from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from marshmallow import Schema, fields, ValidationError, validates

from app.services.transactional_email import send_transactional_email


bp = Blueprint('transactional_emails', __name__)


class SendTransactionalEmailSchema(Schema):
    template_key = fields.Str(required=True)
    to_email = fields.Email(required=True)
    variables = fields.Dict(required=False)
    cc = fields.Str(required=False, allow_none=True)
    bcc = fields.Str(required=False, allow_none=True)

    @validates("template_key")
    def validate_template_key(self, value):
        if not value or not value.strip():
            raise ValidationError("template_key is required")
        if len(value) > 100:
            raise ValidationError("template_key must be <= 100 characters")


send_schema = SendTransactionalEmailSchema()


@bp.route('/send', methods=['POST'])
@jwt_required()
def send():
    claims = get_jwt()
    tenant_id = claims.get('tenant_id')
    if not tenant_id:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = get_jwt_identity()
    payload = request.get_json() or {}

    try:
        data = send_schema.load(payload)
    except ValidationError as err:
        return jsonify({"error": "Validation failed", "details": err.messages}), 400

    try:
        template, result = send_transactional_email(
            template_key=data["template_key"],
            tenant_id=tenant_id,
            to_email=data["to_email"],
            variables=data.get("variables") or {},
            user_id=user_id,
            cc=data.get("cc"),
            bcc=data.get("bcc"),
        )
        return jsonify({
            "success": True,
            "template": {
                "template_id": template.template_id,
                "key": template.key,
                "name": template.name,
            },
            "send_result": result,
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Failed to send transactional email", "details": str(e)}), 500

