from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
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

    def async_add_container_sensors(ids: set[str] | None = None) -> None:
        """Add sensors for new containers."""
        if ids is None:
            ids = set(coordinator.data.keys())

        entities = []
        for container_id in ids:
            entities.append(ArcaneSensor(coordinator, container_id, "State"))
            entities.append(ArcaneSensor(coordinator, container_id, "Image"))

        if entities:
            async_add_entities(entities)

    # Add initial sensors
    async_add_container_sensors()

    # Listen for new containers
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            async_add_container_sensors,
        )
    )


class ArcaneSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_id: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_id = container_id
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{container_id}_{sensor_type.lower()}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        if sensor_type == "State":
            self._attr_icon = "mdi:docker"
        elif sensor_type == "Image":
            self._attr_icon = "mdi:image"

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
    def native_value(self) -> str | None:
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None

        if self._sensor_type == "State":
            return container.get("state")
        if self._sensor_type == "Image":
            return container.get("image")
        return None
