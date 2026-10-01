from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
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

    def add_buttons(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data["containers"])
        entities = []
        for key in keys:
            entities.extend(
                (
                    ArcaneContainerButton(coordinator, key, "restart"),
                    ArcaneContainerButton(coordinator, key, "redeploy"),
                )
            )
        if entities:
            async_add_entities(entities)

    add_buttons()

    project_buttons = []
    for key in coordinator.data.get("projects", {}):
        project_buttons.extend(
            (
                ArcaneProjectButton(coordinator, key, "restart"),
                ArcaneProjectButton(coordinator, key, "redeploy"),
            )
        )
    if project_buttons:
        async_add_entities(project_buttons)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            add_buttons,
        )
    )


class ArcaneContainerButton(CoordinatorEntity, ButtonEntity):
    """Action button for an Arcane container."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_key: str,
        action: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_key = container_key
        self._action = action
        self._attr_unique_id = f"{container_key}_{action}"
        self._attr_has_entity_name = True
        self._attr_name = action.title()
        self._attr_icon = "mdi:restart" if action == "restart" else "mdi:docker"

    @property
    def _container(self) -> dict[str, Any]:
        return self.coordinator.data["containers"].get(self._container_key, {})

    @property
    def device_info(self) -> dict[str, Any]:
        container = self._container
        environment_id = container.get("_environment_id", "unknown")
        environment_name = container.get("_environment_name", environment_id)
        names = container.get("names", [])
        name = (
            names[0].lstrip("/")
            if isinstance(names, list) and names and isinstance(names[0], str)
            else self._container_key
        )
        return {
            "identifiers": {(DOMAIN, self._container_key)},
            "name": name,
            "manufacturer": "Arcane",
            "model": f"Container · {environment_name}",
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    async def async_press(self) -> None:
        container = self._container
        environment_id = container["_environment_id"]
        container_id = container["id"]

        if self._action == "restart":
            await self.coordinator.api.control_container(
                environment_id, container_id, "restart"
            )
        else:
            await self.coordinator.api.redeploy_container(
                environment_id, container_id
            )

        await self.coordinator.async_request_refresh()



class ArcaneProjectButton(CoordinatorEntity, ButtonEntity):
    """Action button for an Arcane Compose project."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        project_key: str,
        action: str,
    ) -> None:
        super().__init__(coordinator)
        self._project_key = project_key
        self._action = action
        self._attr_unique_id = f"project:{project_key}_{action}"
        self._attr_has_entity_name = True
        self._attr_name = action.title()
        self._attr_icon = "mdi:restart" if action == "restart" else "mdi:docker"

    @property
    def _project(self) -> dict[str, Any]:
        return self.coordinator.data.get("projects", {}).get(self._project_key, {})

    @property
    def available(self) -> bool:
        project = self._project
        if not project:
            return False
        if self._action == "redeploy" and project.get("redeployDisabled"):
            return False
        return True

    @property
    def device_info(self) -> dict[str, Any]:
        project = self._project
        environment_id = project.get("_environment_id", "unknown")
        return {
            "identifiers": {(DOMAIN, f"project:{self._project_key}")},
            "name": project.get("name", self._project_key),
            "manufacturer": "Arcane",
            "model": "Docker Compose Project",
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    async def async_press(self) -> None:
        project = self._project
        await self.coordinator.api.control_project(
            project["_environment_id"], project["id"], self._action
        )
        await self.coordinator.async_request_refresh()
