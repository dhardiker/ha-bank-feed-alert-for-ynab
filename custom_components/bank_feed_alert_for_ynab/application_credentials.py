"""Application credentials: the user's own YNAB OAuth application."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN, SETUP_URL, YNAB_DEVELOPER_SETTINGS_URL


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """YNAB's OAuth endpoints."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Placeholders for the credentials dialog."""
    return {
        "setup_url": SETUP_URL,
        "developer_settings_url": YNAB_DEVELOPER_SETTINGS_URL,
    }
