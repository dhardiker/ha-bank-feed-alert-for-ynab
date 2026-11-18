"""Shared entity base: one service device per YNAB plan."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, YNAB_APP_URL
from .coordinator import FeedCoordinator


class FeedEntity(CoordinatorEntity[FeedCoordinator]):
    """An entity on the plan's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FeedCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        plan_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{plan_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, plan_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=YNAB_APP_URL,
        )
