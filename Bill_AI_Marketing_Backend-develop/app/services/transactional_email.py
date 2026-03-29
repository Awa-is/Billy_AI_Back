import re
from typing import Any, Dict, Optional, Tuple

from app.services.email_sender import send_email
from app.models.transactional_email_template import TransactionalEmailTemplate


_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def render(text: str, variables: Dict[str, Any]) -> str:
    if not text:
        return text
    if not variables:
        return text

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        val = variables.get(key, match.group(0))
        return str(val)

    return _VAR_PATTERN.sub(_replace, text)


def get_template(key: str, tenant_id: Optional[str]) -> Optional[TransactionalEmailTemplate]:
    if not key:
        return None

    # Prefer tenant-specific template, then default.
    template = TransactionalEmailTemplate.query.filter(
        TransactionalEmailTemplate.key == key,
        TransactionalEmailTemplate.is_active.is_(True),
        TransactionalEmailTemplate.tenant_id == tenant_id,
    ).first()

    if template:
        return template

    return TransactionalEmailTemplate.query.filter(
        TransactionalEmailTemplate.key == key,
        TransactionalEmailTemplate.is_active.is_(True),
        TransactionalEmailTemplate.is_default.is_(True),
        TransactionalEmailTemplate.tenant_id.is_(None),
    ).first()


def send_transactional_email(
    *,
    template_key: str,
    tenant_id: Optional[str],
    to_email: str,
    variables: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
) -> Tuple[TransactionalEmailTemplate, Dict[str, Any]]:
    template = get_template(template_key, tenant_id)

    # Fallback for password reset if no template is configured.
    if not template and template_key == "password_reset":
        vars_map = variables or {}
        subject = vars_map.get("subject") or "Password reset"
        body = vars_map.get("body") or f"Use this link to reset your password:\n\n{vars_map.get('reset_link', '')}"
        result = send_email(
            recipient_email=to_email,
            subject=subject,
            body=body,
            user_id=user_id,
            cc=cc,
            bcc=bcc,
        )
        # No template record in this path.
        return None, result

    if not template:
        raise ValueError("Transactional email template not found")

    vars_map = variables or {}
    subject = render(template.subject, vars_map)
    body = render(template.body, vars_map)

    result = send_email(
        recipient_email=to_email,
        subject=subject,
        body=body,
        user_id=user_id,
        cc=cc,
        bcc=bcc,
    )
    return template, result

