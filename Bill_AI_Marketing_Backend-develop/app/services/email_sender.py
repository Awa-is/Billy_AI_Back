"""
Email Sender Service

Handles sending emails via OAuth (Microsoft Graph API, Gmail API) with fallback to AWS SES.
"""
import logging
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from typing import Optional, Dict, Any
from datetime import datetime
import html as html_module

from app.config import Config
from app.services.oauth_email_sender import OAuthEmailSender

logger = logging.getLogger(__name__)

# Global SES client (initialized on first use)
_ses_client = None


def convert_body_to_html(body: str) -> str:
    """
    Convert a plain-text email body to a responsive HTML email.

    - Wraps the content in a 100%-width, responsive table layout so email
      clients render the email at full width instead of collapsing it to a
      narrow column.
    - Escapes HTML special characters in the original text so they are
      displayed literally.
    - Converts plain-text newlines to <br> tags to preserve paragraph
      breaks that would otherwise be lost in HTML rendering.
    """
    # Escape any existing HTML entities so they display as literal text
    escaped = html_module.escape(body)
    # Convert newlines to HTML line-breaks
    html_body = escaped.replace('\n', '<br>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body, table {{ margin: 0; padding: 0; width: 100% !important; }}
    img {{ border: 0; display: block; }}
    p {{ margin: 0 0 12px 0; }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0"
         width="100%" style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="padding:20px 24px;font-family:Arial,Helvetica,sans-serif;
                 font-size:14px;line-height:1.6;color:#222222;">
        {html_body}
      </td>
    </tr>
  </table>
</body>
</html>"""


def get_ses_client():
    """Get or create AWS SES client."""
    global _ses_client
    
    if _ses_client is not None:
        return _ses_client
    
    # Validate AWS credentials
    if not Config.AWS_ACCESS_KEY_ID or not Config.AWS_SECRET_ACCESS_KEY:
        raise ValueError("AWS credentials not configured. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in environment.")
    
    if not Config.SES_SENDER_EMAIL:
        raise ValueError("SES sender email not configured. Set SES_SENDER_EMAIL in environment.")
    
    try:
        _ses_client = boto3.client(
            'ses',
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
            region_name=Config.AWS_REGION
        )
        
        # Verify SES client can connect
        _ses_client.get_send_quota()
        logger.info("AWS SES client initialized successfully", extra={"region": Config.AWS_REGION, "sender": Config.SES_SENDER_EMAIL})
        
        return _ses_client
    except (ClientError, BotoCoreError) as e:
        logger.error("Failed to initialize AWS SES client", extra={"error": str(e)})
        raise ValueError(f"AWS SES configuration error: {str(e)}")


def send_email_via_ses(
    recipient_email: str,
    subject: str,
    body: str,
    sender_email: Optional[str] = None,
    user_id: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email via AWS SES.
    """
    if not recipient_email or not recipient_email.strip():
        raise ValueError("Recipient email is required")
    
    if not subject or not subject.strip():
        raise ValueError("Email subject is required")
    
    if not body or not body.strip():
        raise ValueError("Email body is required")
    
    sender = sender_email or Config.SES_SENDER_EMAIL
    if not sender:
        raise ValueError("Sender email not configured")
    
    try:
        ses_client = get_ses_client()
        
        destination = {
            'ToAddresses': [recipient_email.strip()]
        }
        if cc:
             destination['CcAddresses'] = [addr.strip() for addr in cc.split(',') if addr.strip()]
        if bcc:
             destination['BccAddresses'] = [addr.strip() for addr in bcc.split(',') if addr.strip()]

        # Build HTML version of the body so recipients get a properly
        # formatted, full-width email instead of a narrow plain-text column.
        html_body = convert_body_to_html(body)

        # Send email via SES
        response = ses_client.send_email(
            Source=sender,
            Destination=destination,
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    # Plain-text fallback for clients that cannot render HTML
                    'Text': {
                        'Data': body,
                        'Charset': 'UTF-8'
                    },
                    # HTML version — this is what modern email clients display
                    'Html': {
                        'Data': html_body,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        
        message_id = response.get('MessageId')
        logger.info("Email sent successfully via SES", extra={
            "message_id": message_id,
            "recipient": recipient_email,
            "sender": sender
        })
        
        return {
            'success': True,
            'message_id': message_id,
            'response': response
        }
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        
        # Handle specific SES errors
        if error_code == 'MessageRejected':
            logger.warning("Email rejected by SES", extra={
                "recipient": recipient_email,
                "error": error_message
            })
            raise ValueError(f"Email rejected: {error_message}")
        elif error_code == 'MailFromDomainNotVerified':
            raise ValueError("Sender domain not verified in SES")
        elif error_code == 'ConfigurationSetDoesNotExist':
            raise ValueError("SES configuration set does not exist")
        else:
            logger.error("SES API error", extra={
                "error_code": error_code,
                "error_message": error_message,
                "recipient": recipient_email
            })
            raise ValueError(f"AWS SES error ({error_code}): {error_message}")
    
    except BotoCoreError as e:
        logger.error("Boto3 core error", extra={"error": str(e), "recipient": recipient_email})
        raise ValueError(f"AWS connection error: {str(e)}")
    
    except Exception as e:
        logger.exception("Unexpected error sending email", extra={"recipient": recipient_email, "error": str(e)})
        raise ValueError(f"Failed to send email: {str(e)}")


def is_rate_limit_error(error: Exception) -> bool:
    """Check if error is a rate limit error that should be retried."""
    if isinstance(error, ClientError):
        error_code = error.response.get('Error', {}).get('Code', '')
        return error_code in ['Throttling', 'ServiceUnavailable', 'TooManyRequests']
    return False


def is_transient_error(error: Exception) -> bool:
    """Check if error is transient and should be retried."""
    if isinstance(error, (BotoCoreError, ClientError)):
        error_code = getattr(error, 'response', {}).get('Error', {}).get('Code', '') if hasattr(error, 'response') else ''
        return error_code in ['Throttling', 'ServiceUnavailable', 'TooManyRequests', 'RequestTimeout']
    return False


def send_email(
    recipient_email: str,
    subject: str,
    body: str,
    user_id: Optional[str] = None,
    sender_email: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email with OAuth fallback to AWS SES.
    """
    # Try OAuth first if user_id is provided
    if user_id:
        try:
            logger.debug(f"Attempting OAuth email send for user_id={user_id}")
            result = OAuthEmailSender.send_email_via_oauth(
                user_id=user_id,
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc
            )
            
            if result:
                logger.info(f"Email sent via OAuth ({result.get('provider')})", extra={
                    "user_id": user_id,
                    "recipient": recipient_email,
                    "method": "oauth",
                    "provider": result.get('provider')
                })
                return {
                    'success': True,
                    'message_id': result.get('message_id'),
                    'method': 'oauth',
                    'provider': result.get('provider')
                }
            else:
                logger.debug(f"No OAuth provider found for user_id={user_id}, falling back to SES")
        except Exception as e:
            logger.warning(f"OAuth email send failed, falling back to SES: {str(e)}", extra={
                "user_id": user_id,
                "recipient": recipient_email,
                "error": str(e)
            })
            # Continue to SES fallback
    
    # Fallback to AWS SES
    # In local/dev environments without real AWS credentials, avoid raising.
    if not Config.AWS_ACCESS_KEY_ID or not Config.AWS_SECRET_ACCESS_KEY or Config.AWS_ACCESS_KEY_ID == "your-key" or Config.AWS_SECRET_ACCESS_KEY == "your-secret":
        logger.warning(
            "AWS SES credentials not configured or using placeholders; skipping SES send.",
            extra={"recipient": recipient_email},
        )
        return {
            "success": False,
            "message_id": None,
            "method": "ses_disabled",
        }

    logger.debug("Sending email via AWS SES", extra={
        "recipient": recipient_email,
        "method": "ses"
    })
    
    try:
        result = send_email_via_ses(
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            sender_email=sender_email,
            user_id=user_id,
            cc=cc,
            bcc=bcc
        )
        
        logger.info("Email sent via AWS SES", extra={
            "recipient": recipient_email,
            "method": "ses",
            "message_id": result.get('message_id')
        })
        
        return {
            'success': True,
            'message_id': result.get('message_id'),
            'method': 'ses'
        }
    
    except Exception as e:
        logger.error(f"Failed to send email via SES: {str(e)}", extra={
            "recipient": recipient_email,
            "error": str(e)
        })
        raise

