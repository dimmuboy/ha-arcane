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
    CONF_ENV_NAME,
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
    """Return a stable container key within one Arcane environment."""
    return f"{environment_id}:{container_name}"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reject legacy manager-wide entries that cannot select an environment safely."""
    if entry.version < 3:
        environment_id = entry.data.get(CONF_ENV_ID)
        if not environment_id:
            _LOGGER.warning(
                "Arcane config entry %s predates per-environment hubs and must be "
                "removed and added again",
                entry.title,
            )
            return False

        data = dict(entry.data)
        data.setdefault(CONF_ENV_NAME, entry.title)
        host = str(data[CONF_HOST]).rstrip("/").lower()
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            unique_id=f"{host}:{environment_id}",
            version=3,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Arcane environment as a Home Assistant hub."""
    session = async_get_clientsession(hass)
    api = ArcaneAPI(
        entry.data[CONF_HOST],
        entry.data[CONF_API_KEY],
        session,
    )

    coordinator = ArcaneDataUpdateCoordinator(
        hass,
        api,
        entry.entry_id,
        str(entry.data[CONF_ENV_ID]),
        str(entry.data.get(CONF_ENV_NAME, entry.title)),
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to Arcane: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Arcane when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Arcane config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class ArcaneDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinate data for one Arcane environment."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ArcaneAPI,
        entry_id: str,
        environment_id: str,
        environment_name: str,
        scan_interval: int,
    ) -> None:
        self.api = api
        self.entry_id = entry_id
        self.environment_id = environment_id
        self.environment_name = environment_name
        self.known_container_keys: set[str] = set()
        self.known_project_keys: set[str] = set()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{environment_id}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for the configured environment only."""
        try:
            environments_response = await self.api.get_environments()
            environment_list = environments_response.get("data", [])
            if not isinstance(environment_list, list):
                raise UpdateFailed("Arcane returned an invalid environments response")

            environment = next(
                (
                    item
                    for item in environment_list
                    if isinstance(item, dict)
                    and str(item.get("id", "")) == self.environment_id
                ),
                None,
            )
            if environment is None:
                raise UpdateFailed(
                    f"Arcane environment {self.environment_id} is no longer available"
                )

            environment_data = dict(environment)
            environment_data["_environment_id"] = self.environment_id
            environment_data["_environment_name"] = str(
                environment.get("name") or self.environment_name
            )

            try:
                docker_info_response = await self.api.get_docker_info(
                    self.environment_id
                )
                docker_info = docker_info_response.get(
                    "data", docker_info_response
                )
                if isinstance(docker_info, dict):
                    environment_data["_docker_info"] = docker_info
            except Exception as err:
                _LOGGER.debug(
                    "Unable to fetch Docker info for Arcane environment %s: %s",
                    self.environment_id,
                    err,
                )

            vulnerability_counts: dict[str, int | None] = {}
            for severity in ("critical", "high"):
                try:
                    response = await self.api.get_vulnerabilities(
                        self.environment_id, severity
                    )
                    pagination = response.get("pagination", {})
                    value = (
                        pagination.get("totalItems")
                        if isinstance(pagination, dict)
                        else None
                    )
                    vulnerability_counts[severity] = value
                except Exception as err:
                    _LOGGER.debug(
                        "Unable to fetch %s vulnerabilities for environment %s: %s",
                        severity,
                        self.environment_id,
                        err,
                    )
                    vulnerability_counts[severity] = None
            environment_data["_vulnerabilities"] = vulnerability_counts

            projects: dict[str, dict[str, Any]] = {}
            try:
                projects_response = await self.api.get_projects(self.environment_id)
                project_items = projects_response.get("data", [])
                if isinstance(project_items, list):
                    for project in project_items:
                        project_id = str(project.get("id", ""))
                        if not project_id:
                            continue
                        project_key = f"{self.environment_id}:{project_id}"
                        projects[project_key] = {
                            **project,
                            "_environment_id": self.environment_id,
                            "_environment_name": environment_data["_environment_name"],
                        }
            except Exception as err:
                _LOGGER.warning(
                    "Unable to fetch projects for Arcane environment %s: %s",
                    self.environment_id,
                    err,
                )

            project_keys_by_compose_name: dict[str, str] = {}
            for project_key, project in projects.items():
                project_name = project.get("name")
                if isinstance(project_name, str) and project_name:
                    project_keys_by_compose_name[project_name] = project_key

            containers: dict[str, dict[str, Any]] = {}
            try:
                response = await self.api.get_containers(self.environment_id)
            except Exception as err:
                raise UpdateFailed(
                    f"Unable to fetch containers for Arcane environment "
                    f"{self.environment_id}: {err}"
                ) from err

            items = response.get("data", [])
            if not isinstance(items, list):
                raise UpdateFailed("Arcane returned an invalid containers response")

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
                labels = container.get("labels")
                compose_project = (
                    labels.get("com.docker.compose.project")
                    if isinstance(labels, dict)
                    else None
                )
                project_key = (
                    project_keys_by_compose_name.get(compose_project)
                    if isinstance(compose_project, str)
                    else None
                )

                key = container_key(self.environment_id, container_name)
                containers[key] = {
                    **container,
                    "_environment_id": self.environment_id,
                    "_environment_name": environment_data["_environment_name"],
                    "_project_key": project_key,
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

            new_container_keys = set(containers) - self.known_container_keys
            if new_container_keys and self.known_container_keys:
                self.known_container_keys.update(new_container_keys)
                async_dispatcher_send(
                    self.hass,
                    f"{SIGNAL_NEW_CONTAINERS}_{self.entry_id}",
                    new_container_keys,
                )
            elif not self.known_container_keys:
                self.known_container_keys.update(new_container_keys)

            return {
                "environments": {self.environment_id: environment_data},
                "containers": containers,
                "projects": projects,
            }
        except ArcaneAuthError:
            raise
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
