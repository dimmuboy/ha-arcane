from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcaneAPI, ArcaneAuthError
from .const import (
    CONF_API_KEY,
    CONF_ENV_ID,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SIGNAL_NEW_CONTAINERS,
    SIGNAL_NEW_PROJECTS,
)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

_LOGGER = logging.getLogger(__name__)


def container_key(environment_id: str, container_name: str) -> str:
    """Return a stable container key within one Arcane Manager."""
    return f"{environment_id}:{container_name}"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy single-environment config entries."""
    if entry.version == 1:
        data = dict(entry.data)
        data.pop(CONF_ENV_ID, None)
        hass.config_entries.async_update_entry(entry, data=data, version=2)
        _LOGGER.info("Migrated Arcane config entry to multi-environment format")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arcane from a config entry."""
    session = async_get_clientsession(hass)
    api = ArcaneAPI(
        entry.data[CONF_HOST],
        entry.data[CONF_API_KEY],
        session,
    )

    coordinator = ArcaneDataUpdateCoordinator(\n        hass,\n        api,\n        entry.entry_id,\n        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),\n    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to Arcane: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Arcane config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class ArcaneDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinate data for all environments managed by one Arcane Manager."""

    def __init__(\n        self,\n        hass: HomeAssistant,\n        api: ArcaneAPI,\n        entry_id: str,\n        scan_interval: int,\n    ) -> None:
        self.api = api
        self.entry_id = entry_id
        self.known_container_keys: set[str] = set()
        self.known_project_keys: set[str] = set()
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch environments and their containers."""
        try:
            environments_response = await self.api.get_environments()
            environment_list = environments_response.get("data", [])
            if not isinstance(environment_list, list):
                raise UpdateFailed("Arcane returned an invalid environments response")

            environments: dict[str, dict[str, Any]] = {}
            containers: dict[str, dict[str, Any]] = {}
            projects: dict[str, dict[str, Any]] = {}

            for environment in environment_list:
                environment_id = str(environment.get("id", ""))
                if not environment_id:
                    continue

                environment_data = dict(environment)
                try:
                    environment_data["_docker_info"] = await self.api.get_docker_info(
                        environment_id
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "Unable to fetch Docker info for Arcane environment %s: %s",
                        environment_id,
                        err,
                    )

                vulnerability_counts = {}
                for severity in ("critical", "high"):
                    try:
                        response = await self.api.get_vulnerabilities(
                            environment_id, severity
                        )
                        pagination = response.get("pagination", {})
                        vulnerability_counts[severity] = pagination.get(
                            "totalItems", 0
                        )
                    except Exception as err:
                        _LOGGER.debug(
                            "Unable to fetch %s vulnerabilities for environment %s: %s",
                            severity,
                            environment_id,
                            err,
                        )
                environment_data["_vulnerabilities"] = vulnerability_counts
                environments[environment_id] = environment_data

                try:
                    projects_response = await self.api.get_projects(environment_id)
                    project_items = projects_response.get("data", [])
                    if isinstance(project_items, list):
                        for project in project_items:
                            project_id = str(project.get("id", ""))
                            if not project_id:
                                continue
                            project_key = f"{environment_id}:{project_id}"
                            projects[project_key] = {
                                **project,
                                "_environment_id": environment_id,
                                "_environment_name": environment.get(
                                    "name", environment_id
                                ),
                            }
                except Exception as err:
                    _LOGGER.warning(
                        "Unable to fetch projects for Arcane environment %s: %s",
                        environment_id,
                        err,
                    )

                try:
                    response = await self.api.get_containers(environment_id)
                except Exception as err:
                    _LOGGER.warning(
                        "Unable to fetch containers for Arcane environment %s: %s",
                        environment_id,
                        err,
                    )
                    continue

                items = response.get("data", [])
                if not isinstance(items, list):
                    continue

                for container in items:
                    container_id = str(container.get("id", ""))
                    if not container_id:
                        continue
                    names = container.get("names")
                    container_name = (
                        names[0].lstrip("/")
                        if isinstance(names, list) and names and isinstance(names[0], str)
                        else container_id
                    )
                    key = container_key(environment_id, container_name)
                    containers[key] = {
                        **container,
                        "_environment_id": environment_id,
                        "_environment_name": environment.get("name", environment_id),
                    }

            new_project_keys = set(projects) - self.known_project_keys
            if new_project_keys and self.known_project_keys:
                self.known_project_keys.update(new_project_keys)
                async_dispatcher_send(
                    self.hass,
                    f"{SIGNAL_NEW_PROJECTS}_{self.entry_id}",
                    new_project_keys,
                )
            elif not self.known_project_keys:
                self.known_project_keys.update(new_project_keys)

            new_keys = set(containers) - self.known_container_keys
            if new_keys and self.known_container_keys:
                self.known_container_keys.update(new_keys)
                async_dispatcher_send(
                    self.hass,
                    f"{SIGNAL_NEW_CONTAINERS}_{self.entry_id}",
                    new_keys,
                )
            elif not self.known_container_keys:
                self.known_container_keys.update(new_keys)

            return {
                "environments": environments,
                "containers": containers,
                "projects": projects,
            }
        except ArcaneAuthError:
            raise
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
