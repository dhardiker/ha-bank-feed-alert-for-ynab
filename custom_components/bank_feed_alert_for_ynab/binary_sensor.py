"""Problem sensors: the plan as a whole, escalation, and each linked account."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import SERVICE_MARK_RECONNECTED
from .coordinator import FeedConfigEntry, FeedCoordinator
from .entity import FeedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FeedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([NeedsReconnecting(coordinator), ReconnectOverdue(coordinator)])

    # Target an account's sensor to restart that account's clock, or a plan-level sensor for all.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_MARK_RECONNECTED,
        {vol.Optional("when"): cv.datetime},
        "async_mark_reconnected",
    )

    known: set[str] = set()

    @callback
    def _add_new_accounts() -> None:
        new = [aid for aid in coordinator.data.feeds if aid not in known] if coordinator.data else []
        if new:
            known.update(new)
            async_add_entities([AccountFeed(coordinator, aid) for aid in new])

    _add_new_accounts()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_accounts))


def _as_utc(when: datetime | None) -> datetime:
    if when is None:
        return dt_util.utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(when)


class PlanBinarySensor(FeedEntity, BinarySensorEntity):
    """A plan-level sensor: marking it reconnected applies to every linked account."""

    async def async_mark_reconnected(self, when: datetime | None = None) -> None:
        await self.coordinator.async_mark_reconnected(list(self.coordinator.data.feeds), _as_utc(when))


class NeedsReconnecting(PlanBinarySensor):
    """On while any linked account's bank connection is in error."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "needs_reconnecting"

    def __init__(self, coordinator: FeedCoordinator) -> None:
        super().__init__(coordinator, "needs_reconnecting")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.broken)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self.coordinator.data
        return {
            "accounts": [feed.name for feed in snapshot.broken],
            "broken_since": snapshot.broken_since.isoformat() if snapshot.broken_since else None,
        }


class ReconnectOverdue(PlanBinarySensor):
    """On once a connection has been broken for the escalation period (default 3 days)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "reconnect_overdue"

    def __init__(self, coordinator: FeedCoordinator) -> None:
        super().__init__(coordinator, "reconnect_overdue")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.overdue(self.coordinator.escalate_after, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"escalate_after_days": self.coordinator.escalate_after.days}


class AccountFeed(FeedEntity, BinarySensorEntity):
    """One linked account's bank connection; on when it needs reconnecting."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: FeedCoordinator, account_id: str) -> None:
        super().__init__(coordinator, f"account_{account_id}")
        self._account_id = account_id
        self._attr_name = coordinator.data.feeds[account_id].name

    @property
    def available(self) -> bool:
        # Unavailable once the account is closed, deleted or unlinked in YNAB.
        return super().available and self._account_id in self.coordinator.data.feeds

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.feeds[self._account_id].in_error

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        feed = self.coordinator.data.feeds.get(self._account_id)
        if feed is None:
            return {}
        lapse = feed.expected_lapse(self.coordinator.lifetime)
        return {
            "in_error_since": feed.in_error_since.isoformat() if feed.in_error_since else None,
            "last_reconnected": feed.last_reconnected.isoformat() if feed.last_reconnected else None,
            "expected_lapse": lapse.isoformat() if lapse else None,
        }

    async def async_mark_reconnected(self, when: datetime | None = None) -> None:
        await self.coordinator.async_mark_reconnected([self._account_id], _as_utc(when))

    @callback
    def _handle_coordinator_update(self) -> None:
        feed = self.coordinator.data.feeds.get(self._account_id)
        if feed is not None:
            self._attr_name = feed.name
        super()._handle_coordinator_update()
