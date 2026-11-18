"""Polls YNAB for the plan's accounts and keeps the feed state."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import API_BASE, CONF_PLAN_ID, DOMAIN, SCAN_INTERVAL, STORAGE_VERSION
from .feeds import Snapshot, evaluate

_LOGGER = logging.getLogger(__name__)

type FeedConfigEntry = ConfigEntry[FeedCoordinator]


class FeedCoordinator(DataUpdateCoordinator[Snapshot]):
    """One GET /plans/{plan_id}/accounts per poll; remembers error onsets across restarts."""

    config_entry: FeedConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FeedConfigEntry, session: OAuth2Session) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=SCAN_INTERVAL,
        )
        self._session = session
        self._plan_id: str = entry.data[CONF_PLAN_ID]
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
        self._memory: dict[str, Any] | None = None

    async def _async_update_data(self) -> Snapshot:
        if self._memory is None:
            self._memory = await self._store.async_load() or {}
        accounts = await self._fetch_accounts()
        snapshot = evaluate(accounts, self._memory, dt_util.utcnow())
        memory = snapshot.memory()
        if memory != self._memory:
            self._memory = memory
            await self._store.async_save(memory)
        return snapshot

    async def _fetch_accounts(self) -> list[dict[str, Any]]:
        url = f"{API_BASE}/plans/{self._plan_id}/accounts"
        try:
            response = await self._session.async_request("get", url)
            if response.status == HTTPStatus.UNAUTHORIZED:
                raise ConfigEntryAuthFailed("YNAB no longer accepts this authorisation")
            if response.status == HTTPStatus.NOT_FOUND:
                raise UpdateFailed("YNAB could not find this plan; it may have been deleted")
            if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                raise UpdateFailed("YNAB rate limit reached; will retry at the next poll")
            response.raise_for_status()
            body = await response.json()
        except ConfigEntryAuthFailed:
            # Includes Home Assistant's own OAuth2TokenRequestReauthError, which is also
            # a ClientResponseError: let it start reauthentication, don't swallow it below.
            raise
        except ClientResponseError as err:
            # Older Home Assistant versions surface a refused token refresh this way.
            if err.status in (HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED):
                raise ConfigEntryAuthFailed("YNAB refused to refresh the authorisation") from err
            raise UpdateFailed(f"YNAB answered {err.status}") from err
        except (ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Could not reach YNAB: {err}") from err
        try:
            return list(body["data"]["accounts"])
        except (KeyError, TypeError) as err:
            raise UpdateFailed("Unexpected response from YNAB") from err

    async def async_remove_store(self) -> None:
        """Forget the remembered state (the entry is being removed)."""
        await self._store.async_remove()


def storage_key(entry_id: str) -> str:
    """Where an entry's remembered state lives."""
    return f"{DOMAIN}.{entry_id}"
