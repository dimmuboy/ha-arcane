from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_NEW_CONTAINERS
from .__init__ import ArcaneDataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_connect

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def async_add_container_switches(ids: set[str] | None = None) -> None:
        """Add switches for new containers."""
        if ids is None:
            ids = set(coordinator.data.keys())

        entities = []
        for container_id in ids:
            entities.append(ArcaneContainerSwitch(coordinator, container_id))

        if entities:
            async_add_entities(entities)

    # Add initial switches
    async_add_container_switches()

    # Listen for new containers
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            async_add_container_switches,
        )
    )


class ArcaneContainerSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator: ArcaneDataUpdateCoordinator, container_id: str) -> None:
        super().__init__(coordinator)
        self._container_id = container_id
        self._attr_unique_id = f"{container_id}_switch"
        self._attr_has_entity_name = True
        self._attr_name = "Running"
        self._attr_icon = "mdi:docker"
        self._api = coordinator.api

    @property
    def device_info(self) -> dict[str, Any]:
        container = self.coordinator.data.get(self._container_id, {})
        return {
            "identifiers": {(DOMAIN, self._container_id)},
            "name": container.get("names", [self._container_id])[0].lstrip("/"),
            "manufacturer": "Arcane",
            "model": "Container",
            "sw_version": container.get("image"),
        }

    @property
    def is_on(self) -> bool:
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return False
        return container.get("state") == "running"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._api.control_container(self._container_id, "start")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._api.control_container(self._container_id, "stop")
        await self.coordinator.async_request_refresh()
