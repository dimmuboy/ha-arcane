from __future__ import annotations

import asyncio
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

REDEPLOY_POLL_ATTEMPTS = 30
REDEPLOY_POLL_DELAY = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Update entities for Arcane containers."""
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    tracked_keys: set[str] = set()

    def async_add_container_updates(ids: set[str] | None = None) -> None:
        """Add update entities for new containers."""
        if ids is None:
            ids = set(coordinator.data.keys())

        entities = []
        for container_id in ids:
            container = coordinator.data.get(container_id)
            container_key = _container_key(container, container_id)
            if container_key in tracked_keys:
                continue

            tracked_keys.add(container_key)
            entities.append(ArcaneUpdateEntity(coordinator, container_id, container_key))

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


def _first_value(*values: Any) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _container_name(container: dict[str, Any] | None, fallback: str) -> str:
    """Return a stable, readable container name."""
    if container:
        names = container.get("names")
        if isinstance(names, list) and names:
            name = names[0]
            if isinstance(name, str) and name.strip():
                return name.strip().lstrip("/")
    return fallback


def _container_key(container: dict[str, Any] | None, fallback: str) -> str:
    """Return the stable key used to track a redeployed container."""
    return _container_name(container, fallback)


class ArcaneUpdateEntity(CoordinatorEntity, UpdateEntity):
    """Update entity for Docker containers managed via Arcane."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_id: str,
        container_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_id = container_id
        self._container_key = container_key
        self._last_installed_version: str | None = None
        self._last_latest_version: str | None = None
        self._attr_unique_id = f"{container_key}_update"
        self._attr_has_entity_name = True
        self._attr_name = "Update"
        self._attr_icon = "mdi:download"

    @property
    def _container(self) -> dict[str, Any] | None:
        """Return the current container payload from Arcane."""
        container = self.coordinator.data.get(self._container_id)
        if container is not None:
            return container

        for candidate_id, candidate in self.coordinator.data.items():
            if _container_key(candidate, candidate_id) == self._container_key:
                self._container_id = candidate_id
                return candidate

        return None

    @property
    def _update_info(self) -> dict[str, Any]:
        """Return Arcane image update metadata for this container."""
        container = self._container
        if not container:
            return {}
        update_info = container.get("updateInfo")
        if isinstance(update_info, dict):
            return update_info
        return {}

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
            "identifiers": {(DOMAIN, self._container_key)},
            "name": self._container_name(),
            "manufacturer": "Arcane",
            "model": "Container",
            "sw_version": self.installed_version,
        }

    @property
    def installed_version(self) -> str | None:
        """Return Arcane's current image version or digest."""
        container = self._container
        update_info = self._update_info
        version = _first_value(
            update_info.get("currentVersion"),
            update_info.get("currentDigest"),
            container.get("image") if container else None,
        )
        if version:
            self._last_installed_version = version
            return version
        return self._last_installed_version

    @property
    def latest_version(self) -> str | None:
        """Return Arcane's latest available image version or digest."""
        update_info = self._update_info
        version = _first_value(
            update_info.get("latestVersion"),
            update_info.get("latestDigest"),
            self.installed_version,
        )
        if version:
            self._last_latest_version = version
            return version
        return self._last_latest_version or self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the URL to the release notes."""
        return None

    def _container_name(self, fallback: str | None = None) -> str:
        """Return a readable container name."""
        return _container_name(self._container, fallback or self._container_key)

    def _redeploy_confirmed(self, target_version: str | None) -> bool:
        """Return whether Arcane data shows the update is no longer pending."""
        container = self._container
        if container is None:
            return False

        update_info = self._update_info
        if update_info and not update_info.get("hasUpdate", False):
            return True

        if target_version and self.installed_version == target_version:
            return True

        return False

    async def _async_wait_for_redeploy(self, target_version: str | None) -> None:
        """Poll Arcane until the redeploy result is visible to Home Assistant."""
        for attempt in range(1, REDEPLOY_POLL_ATTEMPTS + 1):
            await self.coordinator.async_request_refresh()
            if self._redeploy_confirmed(target_version):
                _LOGGER.info(
                    "Confirmed redeploy for container '%s' after %d poll(s)",
                    self._container_name(),
                    attempt,
                )
                return
            await asyncio.sleep(REDEPLOY_POLL_DELAY)

        raise HomeAssistantError(
            f"Timed out waiting for Arcane to confirm redeploy for container '{self._container_name()}'"
        )

    async def async_install(
        self, version: str | None = None, backup: bool = True, **kwargs: Any
    ) -> None:
        """Install an update by redeploying the container in Arcane."""
        container = self._container
        if not container:
            raise HomeAssistantError(f"Container {self._container_key} not found")

        container_name = self._container_name()
        if self._redeploy_disabled:
            raise HomeAssistantError(
                f"Arcane does not allow redeploying container '{container_name}'"
            )

        target_version = version or self.latest_version
        _LOGGER.info(
            "Installing update for container '%s' (%s) via Arcane redeploy",
            container_name,
            self._container_id,
        )

        try:
            result = await self.coordinator.api.redeploy_container(self._container_id)
            _LOGGER.info(
                "Arcane accepted redeploy for container '%s': %s",
                container_name,
                result,
            )
            await self._async_wait_for_redeploy(target_version)
            _LOGGER.info("Container '%s' update completed successfully", container_name)
        except Exception as err:
            error_msg = f"Failed to redeploy container '{container_name}': {err}"
            _LOGGER.error(error_msg, exc_info=True)
            raise HomeAssistantError(error_msg) from err
