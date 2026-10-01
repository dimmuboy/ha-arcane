from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ArcaneDataUpdateCoordinator
from .const import DOMAIN, SIGNAL_NEW_CONTAINERS
from .entity_helpers import container_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def add_container_switches(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data["containers"])
        async_add_entities(ArcaneContainerSwitch(coordinator, key) for key in keys)

    add_container_switches()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            add_container_switches,
        )
    )


class ArcaneContainerSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(
        self, coordinator: ArcaneDataUpdateCoordinator, container_key: str
    ) -> None:
        super().__init__(coordinator)
        self._container_key = container_key
        self._attr_unique_id = f"{container_key}_switch"
        self._attr_has_entity_name = True
        self._attr_name = "Running"
        self._attr_icon = "mdi:docker"

    @property
    def _container(self) -> dict[str, Any]:
        return self.coordinator.data["containers"].get(self._container_key, {})

    @property
    def name(self) -> str:
        names = self._container.get("names", [])
        container_name = (
            names[0].lstrip("/")
            if isinstance(names, list) and names and isinstance(names[0], str)
            else self._container_key.split(":", 1)[-1]
        )
        return f"{container_name} · Running"

    @property
    def device_info(self) -> dict[str, Any]:
        return container_device_info(self._container)

    @property
    def is_on(self) -> bool:
        return self._container.get("state") == "running"

    async def async_turn_on(self, **kwargs: Any) -> None:
        container = self._container
        await self.coordinator.api.control_container(
            container["_environment_id"], container["id"], "start"
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        container = self._container
        await self.coordinator.api.control_container(
            container["_environment_id"], container["id"], "stop"
        )
        await self.coordinator.async_request_refresh()
