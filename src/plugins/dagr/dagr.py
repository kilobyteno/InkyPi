import logging
import base64
import requests
from PIL import Image
from io import BytesIO
from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class Dagr(BasePlugin):
    """Plugin to fetch and display images from Dagr API device endpoint."""

    def _authenticate(self, base_url, email, activation_code, settings):
        """Authenticate with Dagr API and get device tokens."""
        try:
            url = f"{base_url}/api/v1/device/auth/login"
            payload = {
                "email": email,
                "activation_code": activation_code
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            access_token = data.get("data", {}).get("access_token")
            refresh_token = data.get("data", {}).get("refresh_token")
            if not access_token:
                raise RuntimeError("Failed to get access token from authentication.")
            # Store tokens in settings for persistence
            settings["_dagr_access_token"] = access_token
            settings["_dagr_refresh_token"] = refresh_token
            logger.info("Successfully authenticated with Dagr API")
            return access_token, refresh_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication failed: {e}")
            raise RuntimeError(f"Failed to authenticate with Dagr API: {str(e)}")

    def _refresh_token(self, base_url, settings):
        """Refresh the access token using the refresh token."""
        refresh_token = settings.get("_dagr_refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh token available.")
        try:
            url = f"{base_url}/api/v1/device/auth/token/refresh"
            payload = {
                "refresh_token": refresh_token
            }
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            access_token = data.get("data", {}).get("access_token")
            if not access_token:
                raise RuntimeError("Failed to refresh access token.")
            # Update stored token
            settings["_dagr_access_token"] = access_token
            logger.info("Successfully refreshed access token")
            return access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Token refresh failed: {e}")
            raise RuntimeError(f"Failed to refresh token: {str(e)}")

    def _get_images(self, base_url, settings):
        """Fetch images from Dagr API device endpoint."""
        access_token = settings.get("_dagr_access_token")
        if not access_token:
            raise RuntimeError("Not authenticated. Please authenticate first.")
        
        try:
            url = f"{base_url}/api/v1/device/images"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            response = requests.get(url, headers=headers, timeout=30)
            
            # If unauthorized, try refreshing token once
            if response.status_code == 401:
                logger.info("Access token expired, attempting to refresh...")
                access_token = self._refresh_token(base_url, settings)
                headers["Authorization"] = f"Bearer {access_token}"
                response = requests.get(url, headers=headers, timeout=30)
            
            response.raise_for_status()
            images = response.json().get("data", [])
            
            if not images:
                raise RuntimeError("No images found in device playlist.")
            
            logger.info(f"Fetched {len(images)} images from Dagr API")
            return images
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch images: {e}")
            raise RuntimeError(f"Failed to fetch images from Dagr API: {str(e)}")

    def _decode_image(self, image_data):
        """Decode base64 image data to PIL Image."""
        try:
            # The API returns image_encoded as base64 string
            image_bytes = base64.b64decode(image_data.get("image_encoded"))
            img = Image.open(BytesIO(image_bytes))
            return img
        except Exception as e:
            logger.error(f"Failed to decode image: {e}")
            raise RuntimeError(f"Failed to decode image: {str(e)}")

    def validate_and_authenticate(self, settings, device_config):
        """Validate settings and authenticate with Dagr API. Called when saving settings."""
        # Get base URL from settings
        base_url = settings.get('base_url')
        if not base_url:
            raise RuntimeError("Dagr API base URL is required. Set it in settings.")

        # Get device credentials
        email = settings.get('email')
        if not email:
            raise RuntimeError("Device email is required.")

        activation_code = settings.get('activation_code')
        if not activation_code:
            raise RuntimeError("Device activation code is required.")

        # Authenticate and save tokens
        self._authenticate(base_url, email, activation_code, settings)
        logger.info("Successfully authenticated and saved tokens for Dagr plugin")

    def generate_settings_template(self):
        """Generate settings template with API key requirements."""
        template_params = super().generate_settings_template()
        return template_params

    def generate_image(self, settings, device_config):
        """Generate image from Dagr device API."""
        # Get base URL from settings
        base_url = settings.get('base_url')
        if not base_url:
            raise RuntimeError("Dagr API base URL is required. Set it in settings.")

        # Check if we have a saved token, if not, authenticate if credentials are present
        if not settings.get("_dagr_access_token"):
            email = settings.get('email')
            activation_code = settings.get('activation_code')
            
            if email and activation_code:
                # Authenticate automatically when credentials are present
                logger.info("No token found, authenticating with provided credentials...")
                self._authenticate(base_url, email, activation_code, settings)
                # Note: settings are persisted when device_config.write_config() is called
                # This happens automatically after generate_image in the refresh task
            else:
                raise RuntimeError("Not authenticated. Please provide email and activation code in settings.")

        # Fetch images
        images = self._get_images(base_url, settings)

        if not images:
            raise RuntimeError("No images available from Dagr API.")

        # Select image sequentially
        index = settings.get("index", 0)
        selected_image = images[index % len(images)]
        settings["index"] = (index + 1) % len(images)

        # Decode and return image
        img = self._decode_image(selected_image)
        return img

