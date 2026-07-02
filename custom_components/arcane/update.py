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
    """Set up Update entity for Arcane containers."""
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for container_id in coordinator.data.keys():
        entities.append(ArcaneUpdateEntity(coordinator, container_id))

    if entities:
        async_add_entities(entities)


class ArcaneUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for Docker containers managed via Arcane.
    
    This entity uses the official Home Assistant Update platform to show and manage
    container updates. Updates are detected automatically through Arcane's updateInfo.
    """

    _attr_supported_features = UpdateEntityFeature.INSTALL

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
        """Return the currently installed version (image reference)."""
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        return container.get("image")

    @property
    def latest_version(self) -> str | None:
        """Return the latest available version.
        
        Arcane automatically detects updates through updateInfo field.
        If hasUpdate is true, we return the latest version.
        Otherwise, we return the current version.
        """
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        
        update_info = container.get("updateInfo")
        if update_info and update_info.get("hasUpdate"):
            # Return the latest version info
            latest = update_info.get("latestVersion") or update_info.get("latestDigest")
            if latest:
                return latest
        
        # No update available, return current version
        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the URL to the release notes."""
        container = self.coordinator.data.get(self._container_id)
        if container is None:
            return None
        # Arcane provides update type (digest, tag, error) but not direct release URL
        # Return Arcane dashboard link
        return None

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        """Install an update by redeploying the container.
        
        Uses Arcane's redeploy endpoint which:
        1. Pulls the latest image from registry
        2. Recreates the container with the new image
        3. Preserves all configuration and networks
        """
        try:
            _LOGGER.info(
                "Installing update for container %s via redeploy",
                self._container_id,
            )
            await self.coordinator.api.redeploy_container(self._container_id)
            # Refresh coordinator data after redeployment
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(
                "Error redeploying container %s: %s",
                self._container_id,
                err,
            )
            raise
