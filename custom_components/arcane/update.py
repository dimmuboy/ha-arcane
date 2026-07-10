from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .__init__ import ArcaneDataUpdateCoordinator
from .const import DOMAIN, SIGNAL_NEW_CONTAINERS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Update entities for Arcane containers."""
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    def async_add_container_updates(ids: set[str] | None = None) -> None:
        """Add update entities for new containers."""
        if ids is None:
            ids = set(coordinator.data.keys())

        entities = []
        for container_id in ids:
            entities.append(ArcaneUpdateEntity(coordinator, container_id))

        if entities:
            async_add_entities(entities)

    async_add_container_updates()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            async_add_container_updates,
        )
    )


class ArcaneUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for Docker containers managed via Arcane."""

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
    def _container(self) -> dict[str, Any] | None:
        """Return the current container payload from Arcane."""
        return self.coordinator.data.get(self._container_id)

    @property
    def _redeploy_disabled(self) -> bool:
        """Return whether Arcane blocks redeploy for this container."""
        container = self._container
        return bool(container and container.get("redeployDisabled"))

    @property
    def available(self) -> bool:
        """Return whether this update entity can be used."""
        return self._container is not None and not self._redeploy_disabled

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Return supported features for this update entity."""
        if self._redeploy_disabled:
            return UpdateEntityFeature(0)
        return UpdateEntityFeature.INSTALL

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        container = self._container or {}
        return {
            "identifiers": {(DOMAIN, self._container_id)},
            "name": container.get("names", [self._container_id])[0].lstrip("/"),
            "manufacturer": "Arcane",
            "model": "Container",
            "sw_version": container.get("image"),
        }

    @property
    def installed_version(self) -> str | None:
        """Return the currently installed image reference."""
        container = self._container
        if container is None:
            return None
        return container.get("image")

    @property
    def latest_version(self) -> str | None:
        """Return the latest available image version or digest."""
        container = self._container
        if container is None:
            return None

        update_info = container.get("updateInfo")
        if update_info and update_info.get("hasUpdate"):
            latest = update_info.get("latestVersion") or update_info.get("latestDigest")
            if latest:
                return latest

        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the URL to the release notes."""
        return None

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        """Install an update by redeploying the container in Arcane."""
        container = self._container
        if not container:
            raise HomeAssistantError(f"Container {self._container_id} not found")

        container_name = container.get("names", [self._container_id])[0].lstrip("/")
        if self._redeploy_disabled:
            raise HomeAssistantError(
                f"Arcane does not allow redeploying container '{container_name}'"
            )

        _LOGGER.info(
            "Installing update for container '%s' (%s) via Arcane redeploy",
            container_name,
            self._container_id,
        )

        try:
            result = await self.coordinator.api.redeploy_container(self._container_id)
            _LOGGER.info(
                "Successfully initiated redeploy for container '%s': %s",
                container_name,
                result,
            )
            await self.coordinator.async_request_refresh()
        except Exception as err:
            error_msg = f"Failed to redeploy container '{container_name}': {err}"
            _LOGGER.error(error_msg, exc_info=True)
            raise HomeAssistantError(error_msg) from err
