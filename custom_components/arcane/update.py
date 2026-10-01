from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    tracked_keys: set[str] = set()

    def add_container_updates(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data["containers"])

        entities = []
        for key in keys:
            if key in tracked_keys:
                continue
            tracked_keys.add(key)
            entities.append(ArcaneUpdateEntity(coordinator, key))
        if entities:
            async_add_entities(entities)

    add_container_updates()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            add_container_updates,
        )
    )


def _first_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class ArcaneUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for a Docker container in an Arcane environment."""

    def __init__(
        self, coordinator: ArcaneDataUpdateCoordinator, container_key: str
    ) -> None:
        super().__init__(coordinator)
        self._container_key = container_key
        self._attr_unique_id = f"{container_key}_update"
        self._attr_has_entity_name = True
        self._attr_name = "Update"
        self._attr_icon = "mdi:download"

    @property
    def _container(self) -> dict[str, Any] | None:
        return self.coordinator.data["containers"].get(self._container_key)

    @property
    def _update_info(self) -> dict[str, Any]:
        container = self._container or {}
        value = container.get("updateInfo")
        return value if isinstance(value, dict) else {}

    @property
    def available(self) -> bool:
        return self._container is not None

    @property
    def supported_features(self) -> UpdateEntityFeature:
        return UpdateEntityFeature.INSTALL

    @property
    def device_info(self) -> dict[str, Any]:
        container = self._container or {}
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
            "sw_version": self.installed_version,
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    @property
    def installed_version(self) -> str | None:
        container = self._container or {}
        info = self._update_info
        return _first_value(
            info.get("currentVersion"),
            info.get("currentDigest"),
            container.get("image"),
        )

    @property
    def latest_version(self) -> str | None:
        info = self._update_info
        if info.get("hasUpdate"):
            return _first_value(
                info.get("latestVersion"),
                info.get("latestDigest"),
                self.installed_version,
            )
        return self.installed_version

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        container = self._container
        if not container:
            raise HomeAssistantError(
                f"Container {self._container_key} is not available"
            )

        try:
            await self.coordinator.api.update_container(
                container["_environment_id"], container["id"]
            )
            await self.coordinator.async_request_refresh()
        except Exception as err:
            raise HomeAssistantError(
                f"Failed to update container {self._container_key}: {err}"
            ) from err



class ArcaneProjectUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for an Arcane Compose project."""

    def __init__(
        self, coordinator: ArcaneDataUpdateCoordinator, project_key: str
    ) -> None:
        super().__init__(coordinator)
        self._project_key = project_key
        self._attr_unique_id = f"project:{project_key}_update"
        self._attr_has_entity_name = True
        self._attr_name = "Update"
        self._attr_icon = "mdi:download"

    @property
    def _project(self) -> dict[str, Any]:
        return self.coordinator.data.get("projects", {}).get(self._project_key, {})

    @property
    def supported_features(self) -> UpdateEntityFeature:
        return UpdateEntityFeature.INSTALL

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

    @property
    def installed_version(self) -> str:
        return "Current"

    @property
    def latest_version(self) -> str:
        info = self._project.get("updateInfo")
        if isinstance(info, dict) and info.get("hasUpdate"):
            count = info.get("imagesWithUpdates", 1)
            return f"{count} update(s) available"
        return "Current"

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        project = self._project
        if not project:
            raise HomeAssistantError(
                f"Project {self._project_key} is not available"
            )
        await self.coordinator.api.update_project(
            project["_environment_id"], project["id"]
        )
        await self.coordinator.async_request_refresh()
