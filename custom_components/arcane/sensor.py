from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ArcaneDataUpdateCoordinator
from .const import DOMAIN, SIGNAL_NEW_CONTAINERS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def add_container_sensors(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data["containers"])

        entities = []
        for key in keys:
            entities.extend(
                (
                    ArcaneSensor(coordinator, key, "State"),
                    ArcaneSensor(coordinator, key, "Image"),
                )
            )
        if entities:
            async_add_entities(entities)

    add_container_sensors()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            add_container_sensors,
        )
    )


class ArcaneSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_key: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_key = container_key
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{container_key}_{sensor_type.lower()}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        self._attr_icon = "mdi:docker" if sensor_type == "State" else "mdi:image"

    @property
    def _container(self) -> dict[str, Any]:
        return self.coordinator.data["containers"].get(self._container_key, {})

    @property
    def device_info(self) -> dict[str, Any]:
        container = self._container
        environment_id = container.get("_environment_id", "unknown")
        environment_name = container.get("_environment_name", environment_id)
        name = container.get("names", [self._container_key])[0].lstrip("/")
        return {
            "identifiers": {(DOMAIN, self._container_key)},
            "name": name,
            "manufacturer": "Arcane",
            "model": f"Container · {environment_name}",
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    @property
    def native_value(self) -> str | None:
        container = self._container
        if self._sensor_type == "State":
            return container.get("state")
        if self._sensor_type == "Image":
            return container.get("image")
        return None



class ArcaneEnvironmentSensor(CoordinatorEntity, SensorEntity):
    """Summary sensor for an Arcane environment."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        environment_id: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._environment_id = environment_id
        self._sensor_type = sensor_type
        self._attr_unique_id = f"environment:{environment_id}_{sensor_type.lower()}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        self._attr_icon = "mdi:docker"

    @property
    def _environment(self) -> dict[str, Any]:
        return self.coordinator.data["environments"].get(self._environment_id, {})

    @property
    def device_info(self) -> dict[str, Any]:
        environment = self._environment
        return {
            "identifiers": {(DOMAIN, f"environment:{self._environment_id}")},
            "name": environment.get("name", self._environment_id),
            "manufacturer": "Arcane",
            "model": f"Environment · {environment.get('type', 'Docker')}",
        }

    @property
    def native_value(self) -> int:
        containers = [
            container
            for container in self.coordinator.data["containers"].values()
            if container.get("_environment_id") == self._environment_id
        ]
        if self._sensor_type == "Containers":
            return len(containers)
        if self._sensor_type == "Running":
            return sum(container.get("state") == "running" for container in containers)
        return sum(container.get("state") != "running" for container in containers)
