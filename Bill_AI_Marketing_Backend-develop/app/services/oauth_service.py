"""
OAuth Service for Microsoft Graph API and Gmail API

Handles OAuth flows, token management, and email sending via OAuth.
"""
import logging
import requests
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode, parse_qs, urlparse
import secrets

from app.config import Config
from app.extensions import db
from app.models.user_email_provider import UserEmailProvider
from app.models.user import User

logger = logging.getLogger(__name__)


class OAuthService:
    """Service for handling OAuth flows and token management."""
    
    # Store state values temporarily (in production, use Redis or database)
    _state_store: Dict[str, Dict[str, Any]] = {}
    
    @staticmethod
    def generate_state() -> str:
        """Generate a random state parameter for OAuth flow."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def store_state(state: str, user_id: str, provider: str) -> None:
        """Store state parameter with user_id and provider."""
        OAuthService._state_store[state] = {
            'user_id': user_id,
            'provider': provider,
            'created_at': datetime.utcnow()
        }
        logger.debug(f"Stored OAuth state: {state} for user_id={user_id}, provider={provider}")
    
    @staticmethod
    def validate_and_get_state(state: str) -> Optional[Dict[str, Any]]:
        """Validate state parameter and return stored data."""
        if state not in OAuthService._state_store:
            logger.warning(f"Invalid OAuth state: {state}. Available states: {list(OAuthService._state_store.keys())[:3]}")
            # Clean up old states
            OAuthService._cleanup_old_states()
            return None
        
        stored = OAuthService._state_store.pop(state)
        
        # Check if state expired (older than 10 minutes)
        if stored.get('created_at'):
            age = datetime.utcnow() - stored['created_at']
            if age.total_seconds() > 600:  # 10 minutes
                logger.warning(f"OAuth state expired: {state}, age: {age.total_seconds()} seconds")
                return None
        
        # Clean up old states
        OAuthService._cleanup_old_states()
        return stored
    
    @staticmethod
    def _cleanup_old_states() -> None:
        """Remove state entries older than 10 minutes."""
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        to_remove = [
            state for state, data in OAuthService._state_store.items()
            if data['created_at'] < cutoff
        ]
        for state in to_remove:
            del OAuthService._state_store[state]
    
    @staticmethod
    def get_microsoft_authorization_url(user_id: str) -> Tuple[str, str]:
        """
        Generate Microsoft OAuth authorization URL.
        
        Returns:
            Tuple of (authorization_url, state)
        """
        if not Config.MICROSOFT_CLIENT_ID:
            raise ValueError("Microsoft OAuth not configured. Set MICROSOFT_CLIENT_ID in environment.")
        
        state = OAuthService.generate_state()
        OAuthService.store_state(state, user_id, 'microsoft')
        
        params = {
            'client_id': Config.MICROSOFT_CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': Config.MICROSOFT_REDIRECT_URI,
            'response_mode': 'query',
            'scope': Config.MICROSOFT_SCOPES,
            'state': state,
            'prompt': 'select_account'  # Force account selection
        }
        
        # Determine which endpoint to use based on configuration
        # Check if a specific endpoint is configured, otherwise use /consumers as default
        # /common requires 'All' audience, /consumers works with 'Consumer' audience
        microsoft_endpoint = os.getenv('MICROSOFT_ENDPOINT', 'consumers').lower()
        
        if microsoft_endpoint == 'common':
            # Use /common for both personal and work accounts (requires 'All' audience in Azure)
            endpoint = 'common'
        elif microsoft_endpoint == 'organizations':
            # Use /organizations for work/school accounts only
            endpoint = 'organizations'
        else:
            # Default to /consumers for personal accounts only (works with 'Consumer' audience)
            endpoint = 'consumers'
        
        auth_url = f"https://login.microsoftonline.com/{endpoint}/oauth2/v2.0/authorize?{urlencode(params)}"
        logger.info(f"Using Microsoft endpoint: /{endpoint} (configured: {microsoft_endpoint})")
        logger.info(f"Generated Microsoft OAuth URL for user_id={user_id}")
        return auth_url, state
    
    @staticmethod
    def get_google_authorization_url(user_id: str) -> Tuple[str, str]:
        """
        Generate Google OAuth authorization URL.
        
        Returns:
            Tuple of (authorization_url, state)
        """
        if not Config.GOOGLE_CLIENT_ID:
            raise ValueError("Google OAuth not configured. Set GOOGLE_CLIENT_ID in environment.")
        
        state = OAuthService.generate_state()
        OAuthService.store_state(state, user_id, 'google')
        
        params = {
            'client_id': Config.GOOGLE_CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': Config.GOOGLE_REDIRECT_URI,
            'scope': Config.GOOGLE_SCOPES,
            'access_type': 'offline',  # Required for refresh token
            'prompt': 'consent',  # Force consent to get refresh token
            'state': state
        }
        
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        logger.info(f"Generated Google OAuth URL for user_id={user_id}")
        return auth_url, state
    
    @staticmethod
    def handle_microsoft_callback(code: str, state: str) -> Dict[str, Any]:
        """
        Handle Microsoft OAuth callback and exchange code for tokens.
        
        Returns:
            Dict with provider_id and email
        """
        # Validate state
        state_data = OAuthService.validate_and_get_state(state)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state")
        
        user_id = state_data['user_id']
        
        if not Config.MICROSOFT_CLIENT_ID or not Config.MICROSOFT_CLIENT_SECRET:
            raise ValueError("Microsoft OAuth not configured")
        
        # Determine token endpoint based on configuration
        # Must match the endpoint used in authorization URL
        microsoft_endpoint = os.getenv('MICROSOFT_ENDPOINT', 'consumers').lower()
        if microsoft_endpoint == 'common':
            endpoint = 'common'
        elif microsoft_endpoint == 'organizations':
            endpoint = 'organizations'
        else:
            endpoint = 'consumers'
        
        # Exchange code for tokens
        token_url = f"https://login.microsoftonline.com/{endpoint}/oauth2/v2.0/token"
        token_data = {
            'client_id': Config.MICROSOFT_CLIENT_ID,
            'client_secret': Config.MICROSOFT_CLIENT_SECRET,
            'code': code,
            'redirect_uri': Config.MICROSOFT_REDIRECT_URI,
            'grant_type': 'authorization_code',
            'scope': Config.MICROSOFT_SCOPES
        }
        
        try:
            response = requests.post(token_url, data=token_data, timeout=10)
            response.raise_for_status()
            token_response = response.json()
        except requests.RequestException as e:
            logger.error(f"Microsoft token exchange failed: {str(e)}")
            raise ValueError(f"Failed to exchange OAuth code: {str(e)}")
        
        access_token = token_response.get('access_token')
        refresh_token = token_response.get('refresh_token')
        expires_in = token_response.get('expires_in', 3600)
        
        if not access_token:
            raise ValueError("No access token received from Microsoft")
        
        # Get user email from Microsoft Graph
        try:
            user_info = OAuthService._get_microsoft_user_info(access_token)
            email = user_info.get('mail') or user_info.get('userPrincipalName')
            if not email:
                raise ValueError("Could not retrieve email from Microsoft account")
        except Exception as e:
            logger.error(f"Failed to get Microsoft user info: {str(e)}")
            raise ValueError(f"Failed to retrieve user email: {str(e)}")
        
        # Calculate token expiration
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer
        
        # Encrypt tokens (basic implementation - in production use proper encryption)
        encrypted_access_token = OAuthService._encrypt_token(access_token)
        encrypted_refresh_token = OAuthService._encrypt_token(refresh_token) if refresh_token else None
        
        # Save or update provider
        provider = UserEmailProvider.query.filter_by(
            user_id=user_id,
            email=email,
            provider='microsoft'
        ).first()
        
        if provider:
            provider.access_token = encrypted_access_token
            provider.refresh_token = encrypted_refresh_token
            provider.token_expires_at = token_expires_at
            provider.is_active = True
            provider.email_connected = True
            provider.provider_data = user_info
            provider.updated_at = datetime.utcnow()
        else:
            provider = UserEmailProvider(
                user_id=user_id,
                email=email,
                provider='microsoft',
                access_token=encrypted_access_token,
                refresh_token=encrypted_refresh_token,
                token_expires_at=token_expires_at,
                provider_data=user_info,
                email_connected=True,
                is_active=True
            )
            db.session.add(provider)

        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.email_connected = True

        db.session.commit()
        
        logger.info(f"Microsoft OAuth connected for user_id={user_id}, email={email}")
        
        return {
            'provider_id': provider.provider_id,
            'email': email,
            'provider': 'microsoft'
        }
    
    @staticmethod
    def handle_google_callback(code: str, state: str) -> Dict[str, Any]:
        """
        Handle Google OAuth callback and exchange code for tokens.
        
        Returns:
            Dict with provider_id and email
        """
        # Validate state
        state_data = OAuthService.validate_and_get_state(state)
        if not state_data:
            raise ValueError("Invalid or expired OAuth state")
        
        user_id = state_data['user_id']
        
        if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
            raise ValueError("Google OAuth not configured")
        
        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            'client_id': Config.GOOGLE_CLIENT_ID,
            'client_secret': Config.GOOGLE_CLIENT_SECRET,
            'code': code,
            'redirect_uri': Config.GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        
        try:
            response = requests.post(token_url, data=token_data, timeout=10)
            
            # Check for errors before raising
            if response.status_code != 200:
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    error_data = {'error': response.text}
                
                error_message = error_data.get('error', 'Unknown error')
                error_description = error_data.get('error_description', '')
                
                logger.error(f"Google token exchange failed: {response.status_code} - {error_message}: {error_description}")
                logger.error(f"Request details - redirect_uri: {Config.GOOGLE_REDIRECT_URI}, client_id: {Config.GOOGLE_CLIENT_ID[:20]}...")
                
                # Provide helpful error messages
                if response.status_code == 401:
                    if 'invalid_client' in error_message.lower():
                        raise ValueError("Invalid Google OAuth credentials. Please check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file.")
                    elif 'invalid_grant' in error_message.lower():
                        raise ValueError("OAuth code is invalid or expired. Please start the OAuth flow again.")
                    else:
                        raise ValueError(f"Authentication failed: {error_message}. {error_description}")
                elif response.status_code == 400:
                    if 'redirect_uri_mismatch' in error_message.lower():
                        raise ValueError(f"Redirect URI mismatch. Expected: {Config.GOOGLE_REDIRECT_URI}. Make sure this matches exactly in Google Cloud Console.")
                    else:
                        raise ValueError(f"Bad request: {error_message}. {error_description}")
                else:
                    raise ValueError(f"Failed to exchange OAuth code ({response.status_code}): {error_message}. {error_description}")
            
            response.raise_for_status()
            token_response = response.json()
        except ValueError:
            # Re-raise ValueError as-is (our custom error messages)
            raise
        except requests.RequestException as e:
            logger.error(f"Google token exchange failed: {str(e)}")
            raise ValueError(f"Failed to exchange OAuth code: {str(e)}")
        
        access_token = token_response.get('access_token')
        refresh_token = token_response.get('refresh_token')
        expires_in = token_response.get('expires_in', 3600)
        
        if not access_token:
            raise ValueError("No access token received from Google")
        
        # Get user email from Google API
        try:
            user_info = OAuthService._get_google_user_info(access_token)
            email = user_info.get('email')
            if not email:
                # Try alternative: use the email from the token response if available
                # Some Google APIs return email in token response
                logger.warning("Email not found in userinfo, checking token response")
                raise ValueError("Could not retrieve email from Google account. Make sure userinfo.email scope is granted.")
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                logger.error(f"Unauthorized when getting user info. Access token may be invalid or missing userinfo.email scope.")
                raise ValueError("Failed to retrieve user email: Access token doesn't have permission to read user info. Please ensure 'userinfo.email' scope is included.")
            logger.error(f"Failed to get Google user info: {str(e)}")
            raise ValueError(f"Failed to retrieve user email: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to get Google user info: {str(e)}")
            raise ValueError(f"Failed to retrieve user email: {str(e)}")
        
        # Calculate token expiration
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer
        
        # Encrypt tokens
        encrypted_access_token = OAuthService._encrypt_token(access_token)
        encrypted_refresh_token = OAuthService._encrypt_token(refresh_token) if refresh_token else None
        
        # Save or update provider
        provider = UserEmailProvider.query.filter_by(
            user_id=user_id,
            email=email,
            provider='google'
        ).first()
        
        if provider:
            provider.access_token = encrypted_access_token
            provider.refresh_token = encrypted_refresh_token
            provider.token_expires_at = token_expires_at
            provider.is_active = True
            provider.email_connected = True
            provider.provider_data = user_info
            provider.updated_at = datetime.utcnow()
        else:
            provider = UserEmailProvider(
                user_id=user_id,
                email=email,
                provider='google',
                access_token=encrypted_access_token,
                refresh_token=encrypted_refresh_token,
                token_expires_at=token_expires_at,
                provider_data=user_info,
                email_connected=True,
                is_active=True
            )
            db.session.add(provider)

        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.email_connected = True

        db.session.commit()
        
        logger.info(f"Google OAuth connected for user_id={user_id}, email={email}")
        
        return {
            'provider_id': provider.provider_id,
            'email': email,
            'provider': 'google'
        }
    
    @staticmethod
    def _get_microsoft_user_info(access_token: str) -> Dict[str, Any]:
        """Get user info from Microsoft Graph API."""
        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                error_data = {}
                try:
                    error_data = e.response.json()
                except:
                    error_data = {'error': e.response.text}
                
                logger.error(f"401 Unauthorized when getting user info: {error_data}")
                logger.error("Make sure 'User.Read' scope is included in MICROSOFT_SCOPES")
                logger.error("And that the permission is granted in Azure Portal")
                raise ValueError(
                    "Failed to retrieve user email: Access token doesn't have permission to read user info. "
                    "Please ensure 'User.Read' scope is included and permission is granted in Azure Portal."
                ) from e
            raise
    
    @staticmethod
    def _get_google_user_info(access_token: str) -> Dict[str, Any]:
        """Get user info from Google API."""
        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            response = requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 401:
                error_data = {}
                try:
                    error_data = e.response.json()
                except:
                    error_data = {'error': e.response.text}
                logger.error(f"401 Unauthorized when getting user info: {error_data}")
                logger.error("Make sure 'userinfo.email' scope is included in GOOGLE_SCOPES")
                raise  # Re-raise to be caught by caller
            raise
    
    @staticmethod
    def _encrypt_token(token: str) -> str:
        """
        Encrypt token (basic implementation).
        In production, use proper encryption like Fernet or AES.
        For now, we'll use base64 encoding as a placeholder.
        Note: This is NOT secure encryption - implement proper encryption in production!
        """
        # TODO: Implement proper encryption using cryptography library
        # For now, using base64 as placeholder (NOT SECURE - replace in production)
        return base64.b64encode(token.encode('utf-8')).decode('utf-8')
    
    @staticmethod
    def _decrypt_token(encrypted_token: str) -> str:
        """Decrypt token."""
        # TODO: Implement proper decryption
        try:
            return base64.b64decode(encrypted_token.encode('utf-8')).decode('utf-8')
        except Exception as e:
            logger.error(f"Token decryption failed: {str(e)}")
            raise ValueError(f"Failed to decrypt token: {str(e)}")
    
    @staticmethod
    def refresh_microsoft_token(provider: UserEmailProvider) -> bool:
        """Refresh Microsoft access token using refresh token."""
        if not provider.refresh_token:
            logger.warning(f"No refresh token available for provider_id={provider.provider_id}")
            return False
        
        if not Config.MICROSOFT_CLIENT_ID or not Config.MICROSOFT_CLIENT_SECRET:
            logger.error("Microsoft OAuth not configured")
            return False
        
        try:
            decrypted_refresh_token = OAuthService._decrypt_token(provider.refresh_token)
        except Exception as e:
            logger.error(f"Failed to decrypt refresh token: {str(e)}")
            return False
        
        # Determine token endpoint based on configuration
        # Must match the endpoint used in authorization URL
        microsoft_endpoint = os.getenv('MICROSOFT_ENDPOINT', 'consumers').lower()
        if microsoft_endpoint == 'common':
            endpoint = 'common'
        elif microsoft_endpoint == 'organizations':
            endpoint = 'organizations'
        else:
            endpoint = 'consumers'
        
        token_url = f"https://login.microsoftonline.com/{endpoint}/oauth2/v2.0/token"
        token_data = {
            'client_id': Config.MICROSOFT_CLIENT_ID,
            'client_secret': Config.MICROSOFT_CLIENT_SECRET,
            'refresh_token': decrypted_refresh_token,
            'grant_type': 'refresh_token',
            'scope': Config.MICROSOFT_SCOPES
        }
        
        try:
            response = requests.post(token_url, data=token_data, timeout=10)
            response.raise_for_status()
            token_response = response.json()
        except requests.RequestException as e:
            logger.error(f"Microsoft token refresh failed: {str(e)}")
            return False
        
        access_token = token_response.get('access_token')
        refresh_token = token_response.get('refresh_token') or decrypted_refresh_token
        expires_in = token_response.get('expires_in', 3600)
        
        if not access_token:
            logger.error("No access token received from Microsoft refresh")
            return False
        
        # Update provider
        provider.access_token = OAuthService._encrypt_token(access_token)
        if token_response.get('refresh_token'):
            provider.refresh_token = OAuthService._encrypt_token(refresh_token)
        provider.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)
        provider.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Microsoft token refreshed for provider_id={provider.provider_id}")
        return True
    
    @staticmethod
    def refresh_google_token(provider: UserEmailProvider) -> bool:
        """Refresh Google access token using refresh token."""
        if not provider.refresh_token:
            logger.warning(f"No refresh token available for provider_id={provider.provider_id}")
            return False
        
        if not Config.GOOGLE_CLIENT_ID or not Config.GOOGLE_CLIENT_SECRET:
            logger.error("Google OAuth not configured")
            return False
        
        try:
            decrypted_refresh_token = OAuthService._decrypt_token(provider.refresh_token)
        except Exception as e:
            logger.error(f"Failed to decrypt refresh token: {str(e)}")
            return False
        
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            'client_id': Config.GOOGLE_CLIENT_ID,
            'client_secret': Config.GOOGLE_CLIENT_SECRET,
            'refresh_token': decrypted_refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(token_url, data=token_data, timeout=10)
            response.raise_for_status()
            token_response = response.json()
        except requests.RequestException as e:
            logger.error(f"Google token refresh failed: {str(e)}")
            return False
        
        access_token = token_response.get('access_token')
        expires_in = token_response.get('expires_in', 3600)
        
        if not access_token:
            logger.error("No access token received from Google refresh")
            return False
        
        # Update provider
        provider.access_token = OAuthService._encrypt_token(access_token)
        # Google may return a new refresh token, but usually keeps the same one
        if token_response.get('refresh_token'):
            provider.refresh_token = OAuthService._encrypt_token(token_response['refresh_token'])
        provider.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)
        provider.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Google token refreshed for provider_id={provider.provider_id}")
        return True
    
    @staticmethod
    def get_valid_access_token(provider: UserEmailProvider) -> Optional[str]:
        """
        Get a valid access token for the provider, refreshing if necessary.
        
        Returns:
            Decrypted access token or None if refresh failed
        """
        # Check if token is expired or will expire soon (within 5 minutes)
        if provider.token_expires_at and provider.token_expires_at <= datetime.utcnow() + timedelta(minutes=5):
            logger.debug(f"Token expired or expiring soon for provider_id={provider.provider_id}, refreshing...")
            if provider.provider == 'microsoft':
                success = OAuthService.refresh_microsoft_token(provider)
            elif provider.provider == 'google':
                success = OAuthService.refresh_google_token(provider)
            else:
                logger.error(f"Unknown provider: {provider.provider}")
                return None
            
            if not success:
                logger.error(f"Failed to refresh token for provider_id={provider.provider_id}")
                return None
        
        try:
            return OAuthService._decrypt_token(provider.access_token)
        except Exception as e:
            logger.error(f"Failed to decrypt access token: {str(e)}")
            return None

