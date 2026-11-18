"""Bank Feed Alert for YNAB: tells Home Assistant when YNAB's bank connections need reconnecting."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow, issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_VERSION, YNAB_APP_URL
from .coordinator import FeedConfigEntry, FeedCoordinator, storage_key

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: FeedConfigEntry) -> bool:
    """Set up a plan's feed monitoring."""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    coordinator = FeedCoordinator(hass, entry, session)
    coordinator.options_at_setup = dict(entry.options)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    @callback
    def _sync() -> None:
        sync_repair_issue(hass, entry)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FeedConfigEntry) -> bool:
    """Unload a config entry. Any open repair issue stays until the next load re-checks it."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FeedConfigEntry) -> None:
    """The entry is gone: drop its repair issue and remembered state."""
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry.entry_id))
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_options_updated(hass: HomeAssistant, entry: FeedConfigEntry) -> None:
    # Update listeners fire for every entry update, including Home Assistant saving a refreshed
    # OAuth token (every couple of hours). Reload only when the options really changed.
    if dict(entry.options) != entry.runtime_data.options_at_setup:
        await hass.config_entries.async_reload(entry.entry_id)


def issue_id(entry_id: str) -> str:
    """One repair issue per plan."""
    return f"reconnect_{entry_id}"


@callback
def sync_repair_issue(hass: HomeAssistant, entry: FeedConfigEntry) -> None:
    """Raise, escalate or clear the plan's repair issue to match the latest poll."""
    coordinator = entry.runtime_data
    snapshot = coordinator.data
    if snapshot is None or not snapshot.broken:
        ir.async_delete_issue(hass, DOMAIN, issue_id(entry.entry_id))
        return
    overdue = snapshot.overdue(coordinator.escalate_after, dt_util.utcnow())
    since = dt_util.as_local(snapshot.broken_since) if snapshot.broken_since else None
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR if overdue else ir.IssueSeverity.WARNING,
        translation_key="reconnect_overdue" if overdue else "reconnect_needed",
        translation_placeholders={
            "plan": entry.title,
            "accounts": ", ".join(feed.name for feed in snapshot.broken),
            "count": str(len(snapshot.broken)),
            "since": f"{since.day} {since:%b %Y %H:%M}" if since else "unknown",
            "days": str(coordinator.escalate_after.days),
        },
        learn_more_url=YNAB_APP_URL,
    )
