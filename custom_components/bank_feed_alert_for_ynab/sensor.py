"""Sensors: how many feeds are broken, since when, and when YNAB was last asked."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FeedConfigEntry, FeedCoordinator
from .entity import FeedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FeedConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([BrokenCount(coordinator), BrokenSince(coordinator), LastChecked(coordinator)])


class BrokenCount(FeedEntity, SensorEntity):
    """Linked accounts whose connection is in error."""

    _attr_translation_key = "broken_feeds"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FeedCoordinator) -> None:
        super().__init__(coordinator, "broken_feeds")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.broken)


class BrokenSince(FeedEntity, SensorEntity):
    """When the longest-running current error was first seen; unknown while all is well."""

    _attr_translation_key = "broken_since"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: FeedCoordinator) -> None:
        super().__init__(coordinator, "broken_since")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.broken_since


class LastChecked(FeedEntity, SensorEntity):
    """When YNAB last answered - proof the watch itself is working."""

    _attr_translation_key = "last_checked"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FeedCoordinator) -> None:
        super().__init__(coordinator, "last_checked")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.checked_at
