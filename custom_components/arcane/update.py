from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .__init__ import ArcaneDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for container_id in coordinator.data.keys():
        entities.append(ArcaneUpdateEntity(coordinator, container_id))

    if entities:
        async_add_entities(entities)


class ArcaneUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for Docker containers managed via Arcane."""

    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION
    )

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_id = container_id
        self._attr_unique_id = f"{container_id}_update"
        self._attr_has_entity_name = True
        self._attr_name = "Update"
        self._attr_icon = "mdi:download"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        container = self.coordinator.data.get(self._container_id, {})
        return {
            "identifiers": {(DOMAIN, self._container_id)},
            "name": container.get("names", [self._container_id])[0].lstrip("/"),
            "manufacturer": "Arcane",
            "model": "Container",
            "sw_version": container.get("image"),
        }

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed version."""
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        return container.get("image")

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version."""
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        # Check if update is available and return the new version
        if container.get("update_available"):
            return container.get("latest_image")
        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the URL to the release."""
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        return container.get("release_url")

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        """Install an update."""
        try:
            _LOGGER.info(
                "Installing update for container %s (backup=%s)",
                self._container_id,
                backup,
            )
            await self.coordinator.api.install_update(self._container_id)
            # Refresh coordinator data after installation
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(
                "Error installing update for container %s: %s",
                self._container_id,
                err,
            )
            raise
