from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArcaneAPI
from .const import CONF_API_KEY, CONF_ENV_ID, CONF_HOST, DEFAULT_SCAN_INTERVAL, DOMAIN, SIGNAL_NEW_CONTAINERS
from homeassistant.helpers.dispatcher import async_dispatcher_send

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    api_key = entry.data[CONF_API_KEY]
    env_id = entry.data[CONF_ENV_ID]

    session = async_get_clientsession(hass)
    api = ArcaneAPI(host, api_key, env_id, session)

    coordinator = ArcaneDataUpdateCoordinator(hass, api)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to Arcane: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class ArcaneDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: ArcaneAPI) -> None:
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.known_container_ids: set[str] = set()

    async def _async_update_data(self):
        try:
            containers_response = await self.api.get_containers()
            containers = containers_response.get("data", [])
            data = {container["id"]: container for container in containers}

            # Check for new containers
            new_ids = set(data.keys()) - self.known_container_ids
            if new_ids and self.known_container_ids:
                self.known_container_ids.update(new_ids)
                async_dispatcher_send(
                    self.hass, f"{SIGNAL_NEW_CONTAINERS}_{self.config_entry.entry_id}"
                )
            elif not self.known_container_ids:
                self.known_container_ids.update(new_ids)

            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
