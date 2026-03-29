"""
OAuth Email Sender Service

Handles sending emails via Microsoft Graph API and Gmail API using OAuth tokens.
"""
import logging
import requests
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any

# Lazy import to avoid circular dependency; resolved at call time.
def _get_html_converter():
    from app.services.email_sender import convert_body_to_html
    return convert_body_to_html

from app.extensions import db
from app.models.user_email_provider import UserEmailProvider
from app.services.oauth_service import OAuthService

logger = logging.getLogger(__name__)


class OAuthEmailSender:
    """Service for sending emails via OAuth (Microsoft Graph API and Gmail API)."""
    
    @staticmethod
    def send_email_via_microsoft(
        access_token: str,
        sender_email: str,
        recipient_email: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email via Microsoft Graph API."""
        if not recipient_email or not recipient_email.strip():
            raise ValueError("Recipient email is required")
        
        if not subject or not subject.strip():
            raise ValueError("Email subject is required")
        
        if not body or not body.strip():
            raise ValueError("Email body is required")
        
        # Convert plain-text body to HTML so the message renders at full
        # width in the recipient's email client.
        convert_body_to_html = _get_html_converter()
        html_body = convert_body_to_html(body)

        # Create email message for Microsoft Graph API
        message = {
            "message": {
                "subject": subject,
                "body": {
                    # Use HTML so the email client renders it as rich content
                    # at full width rather than collapsing it as plain text.
                    "contentType": "HTML",
                    "content": html_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": recipient_email.strip()
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }

        if cc:
             message["message"]["ccRecipients"] = [
                 {"emailAddress": {"address": addr.strip()}}
                 for addr in cc.split(',') if addr.strip()
             ]
        
        if bcc:
             message["message"]["bccRecipients"] = [
                 {"emailAddress": {"address": addr.strip()}}
                 for addr in bcc.split(',') if addr.strip()
             ]
        
        # Send email via Microsoft Graph API
        url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            response = requests.post(url, json=message, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Microsoft Graph API doesn't return a message_id in the response
            # We'll use the request ID or generate one
            message_id = response.headers.get('request-id', f'msg-{sender_email}-{recipient_email}')
            
            logger.info("Email sent successfully via Microsoft Graph API", extra={
                "sender": sender_email,
                "recipient": recipient_email,
                "message_id": message_id
            })
            
            return {
                'success': True,
                'message_id': message_id,
                'provider': 'microsoft'
            }
            
        except requests.HTTPError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except:
                error_data = {'error': {'message': str(e)}}
            
            error_message = error_data.get('error', {}).get('message', str(e))
            logger.error("Microsoft Graph API error", extra={
                "error": error_message,
                "sender": sender_email,
                "recipient": recipient_email,
                "status_code": e.response.status_code
            })
            raise ValueError(f"Microsoft Graph API error: {error_message}")
        
        except requests.RequestException as e:
            logger.error("Microsoft Graph API request error", extra={
                "error": str(e),
                "sender": sender_email,
                "recipient": recipient_email
            })
            raise ValueError(f"Failed to send email via Microsoft: {str(e)}")
    
    @staticmethod
    def send_email_via_gmail(
        access_token: str,
        sender_email: str,
        recipient_email: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email via Gmail API."""
        if not recipient_email or not recipient_email.strip():
            raise ValueError("Recipient email is required")
        
        if not subject or not subject.strip():
            raise ValueError("Email subject is required")
        
        if not body or not body.strip():
            raise ValueError("Email body is required")
        
        # Convert plain-text body to HTML for a full-width, properly
        # formatted email in the recipient's inbox.
        convert_body_to_html = _get_html_converter()
        html_body = convert_body_to_html(body)

        # Build a multipart/alternative message so clients that cannot
        # render HTML fall back gracefully to the plain-text part.
        message = MIMEMultipart('alternative')
        message['to'] = recipient_email.strip()
        message['from'] = sender_email
        message['subject'] = subject

        if cc:
             message['Cc'] = cc
        if bcc:
             message['Bcc'] = bcc

        # Attach plain-text first (lowest preference), then HTML (highest)
        part_text = MIMEText(body, 'plain', 'utf-8')
        part_html = MIMEText(html_body, 'html', 'utf-8')
        message.attach(part_text)
        message.attach(part_html)

        # Encode message in base64url format (Gmail API requirement)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        # Send email via Gmail API
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'raw': raw_message
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            message_id = result.get('id', f'gmail-{sender_email}-{recipient_email}')
            
            logger.info("Email sent successfully via Gmail API", extra={
                "sender": sender_email,
                "recipient": recipient_email,
                "message_id": message_id
            })
            
            return {
                'success': True,
                'message_id': message_id,
                'provider': 'google'
            }
            
        except requests.HTTPError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except:
                error_data = {'error': {'message': str(e)}}
            
            error_message = error_data.get('error', {}).get('message', str(e))
            logger.error("Gmail API error", extra={
                "error": error_message,
                "sender": sender_email,
                "recipient": recipient_email,
                "status_code": e.response.status_code
            })
            raise ValueError(f"Gmail API error: {error_message}")
        
        except requests.RequestException as e:
            logger.error("Gmail API request error", extra={
                "error": str(e),
                "sender": sender_email,
                "recipient": recipient_email
            })
            raise ValueError(f"Failed to send email via Gmail: {str(e)}")
    
    @staticmethod
    def send_email_via_oauth(
        user_id: str,
        recipient_email: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email via OAuth (Microsoft or Google) for a user."""
        # Primary query: find a fully-connected active provider
        provider = (
            UserEmailProvider.query
            .filter(
                UserEmailProvider.user_id == user_id,
                UserEmailProvider.is_active.is_(True),
                UserEmailProvider.email_connected.is_(True),
                UserEmailProvider.access_token.isnot(None),
            )
            .order_by(UserEmailProvider.updated_at.desc())
            .first()
        )

        # Fallback: if no provider found with email_connected=True, try any
        # active provider that has a token. This handles the case where the
        # migration backfill hasn't run yet or email_connected was incorrectly
        # set to False for an already-connected account.
        if not provider:
            provider = (
                UserEmailProvider.query
                .filter(
                    UserEmailProvider.user_id == user_id,
                    UserEmailProvider.is_active.is_(True),
                    UserEmailProvider.access_token.isnot(None),
                )
                .order_by(UserEmailProvider.updated_at.desc())
                .first()
            )
            if provider:
                logger.warning(
                    f"Found active provider via fallback (email_connected=False) for "
                    f"user_id={user_id}. Auto-healing email_connected flag."
                )
                # Auto-heal: set email_connected=True so future queries work correctly
                try:
                    provider.email_connected = True
                    db.session.commit()
                except Exception as heal_err:
                    logger.error(f"Failed to auto-heal email_connected flag: {heal_err}")
                    db.session.rollback()

        if not provider:
            logger.debug(f"No active OAuth provider found for user_id={user_id}")
            return None
        
        # Get valid access token (refresh if needed)
        access_token = OAuthService.get_valid_access_token(provider)
        if not access_token:
            logger.error(f"Failed to get valid access token for provider_id={provider.provider_id}")
            raise ValueError("Failed to get valid OAuth access token")
        
        # Send email via appropriate provider
        if provider.provider == 'microsoft':
            result = OAuthEmailSender.send_email_via_microsoft(
                access_token=access_token,
                sender_email=provider.email,
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc
            )
        elif provider.provider == 'google':
            result = OAuthEmailSender.send_email_via_gmail(
                access_token=access_token,
                sender_email=provider.email,
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc
            )
        else:
            logger.error(f"Unknown provider: {provider.provider}")
            raise ValueError(f"Unknown OAuth provider: {provider.provider}")
        
        logger.info(f"Email sent via OAuth ({provider.provider})", extra={
            "user_id": user_id,
            "provider_id": provider.provider_id,
            "sender": provider.email,
            "recipient": recipient_email,
            "message_id": result.get('message_id')
        })
        
        return result

