"""Diagnostics: the feed state, with the OAuth token redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import FeedConfigEntry
from .feeds import cycles

TO_REDACT = {"token", "access_token", "refresh_token"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FeedConfigEntry) -> dict[str, Any]:
    snapshot = entry.runtime_data.data
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "checked_at": snapshot.checked_at.isoformat() if snapshot else None,
        "feeds": [
            {
                "name": feed.name,
                "in_error": feed.in_error,
                "in_error_since": feed.in_error_since.isoformat() if feed.in_error_since else None,
                "last_reconnected": feed.last_reconnected.isoformat() if feed.last_reconnected else None,
            }
            for feed in (snapshot.feeds.values() if snapshot else [])
        ],
        # Every observed break and reconnection, bracketed by the checks either side, and the
        # connection lifetimes they imply - the data for learning when connections really lapse.
        "history": [event.as_dict() for event in (snapshot.history if snapshot else ())],
        "cycles": cycles(snapshot.history) if snapshot else [],
        "check_interval": str(entry.runtime_data.update_interval),
    }
