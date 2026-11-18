"""Polls YNAB for the plan's accounts and keeps the feed state."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
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

from .const import (
    API_BASE,
    CONF_CHECK_INTERVAL_HOURS,
    CONF_CONNECTION_LIFETIME_DAYS,
    CONF_ESCALATE_AFTER_DAYS,
    CONF_PLAN_ID,
    DEFAULT_CHECK_INTERVAL_HOURS,
    DEFAULT_CONNECTION_LIFETIME_DAYS,
    DEFAULT_ESCALATE_AFTER_DAYS,
    DOMAIN,
    FAST_INTERVAL,
    STORAGE_VERSION,
    WINDOW_AFTER_LAPSE,
    WINDOW_BEFORE_LAPSE,
)
from .feeds import Snapshot, evaluate, next_interval

_LOGGER = logging.getLogger(__name__)

type FeedConfigEntry = ConfigEntry[FeedCoordinator]


class FeedCoordinator(DataUpdateCoordinator[Snapshot]):
    """One GET /plans/{plan_id}/accounts per check; remembers onsets and reconnections across restarts.

    The interval adapts after every check: the configured normal interval while all is well,
    FAST_INTERVAL while a feed is broken, around a projected lapse, or after a failed check.
    """

    config_entry: FeedConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FeedConfigEntry, session: OAuth2Session) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=FAST_INTERVAL,
        )
        self._session = session
        self._plan_id: str = entry.data[CONF_PLAN_ID]
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
        self._memory: dict[str, Any] | None = None
        self._accounts: list[dict[str, Any]] = []

    # Options -----------------------------------------------------------------------------

    @property
    def escalate_after(self) -> timedelta:
        """How long a broken feed may wait before the alert escalates (0: at once)."""
        return timedelta(days=self.config_entry.options.get(CONF_ESCALATE_AFTER_DAYS, DEFAULT_ESCALATE_AFTER_DAYS))

    @property
    def normal_interval(self) -> timedelta:
        return timedelta(
            hours=self.config_entry.options.get(CONF_CHECK_INTERVAL_HOURS, DEFAULT_CHECK_INTERVAL_HOURS)
        )

    @property
    def lifetime(self) -> timedelta | None:
        """How long a bank connection lasts before it must be renewed; None: don't project."""
        days = self.config_entry.options.get(CONF_CONNECTION_LIFETIME_DAYS, DEFAULT_CONNECTION_LIFETIME_DAYS)
        return timedelta(days=days) if days else None

    # Polling -----------------------------------------------------------------------------

    async def _async_update_data(self) -> Snapshot:
        await self._async_load_memory()
        try:
            self._accounts = await self._fetch_accounts()
        except UpdateFailed:
            self.update_interval = FAST_INTERVAL  # retry soon, not in hours
            raise
        snapshot = evaluate(self._accounts, self._memory, dt_util.utcnow())
        await self._async_remember(snapshot)
        self._schedule_next(snapshot)
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
                raise UpdateFailed("YNAB rate limit reached; will retry shortly")
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

    def _schedule_next(self, snapshot: Snapshot) -> None:
        self.update_interval = next_interval(
            snapshot,
            dt_util.utcnow(),
            normal=self.normal_interval,
            fast=FAST_INTERVAL,
            lifetime=self.lifetime,
            before=WINDOW_BEFORE_LAPSE,
            after=WINDOW_AFTER_LAPSE,
        )

    # Memory ------------------------------------------------------------------------------

    async def _async_load_memory(self) -> None:
        if self._memory is None:
            self._memory = await self._store.async_load() or {}

    async def _async_remember(self, snapshot: Snapshot) -> None:
        memory = snapshot.memory()
        if memory != self._memory:
            self._memory = memory
            await self._store.async_save(memory)

    async def async_mark_reconnected(self, account_ids: Iterable[str], when: datetime) -> None:
        """The user renewed these connections (early, or before installing): restart their clocks."""
        if self.data is None:
            return
        await self._async_load_memory()
        assert self._memory is not None
        stamp = dt_util.as_utc(when).isoformat()
        for account_id in account_ids:
            if account_id in self.data.feeds:
                self._memory.setdefault(account_id, {})["last_reconnected"] = stamp
        await self._store.async_save(self._memory)
        snapshot = evaluate(self._accounts, self._memory, self.data.checked_at)
        self._schedule_next(snapshot)
        self.async_set_updated_data(snapshot)

    async def async_remove_store(self) -> None:
        """Forget the remembered state (the entry is being removed)."""
        await self._store.async_remove()


def storage_key(entry_id: str) -> str:
    """Where an entry's remembered state lives."""
    return f"{DOMAIN}.{entry_id}"
