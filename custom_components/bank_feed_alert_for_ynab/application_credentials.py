"""Application credentials: the user's own YNAB OAuth application."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import (
    MY_REDIRECT_URL,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
    PRIVACY_URL,
    PROJECT_URL,
    YNAB_DEVELOPER_SETTINGS_URL,
)


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """YNAB's OAuth endpoints."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Placeholders for the credentials dialog."""
    return {
        "developer_settings_url": YNAB_DEVELOPER_SETTINGS_URL,
        "redirect_url": MY_REDIRECT_URL,
        "website_url": PROJECT_URL,
        "privacy_url": PRIVACY_URL,
    }
