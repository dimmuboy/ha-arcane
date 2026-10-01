"""Diagnostics support for Arcane."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_API_KEY, DOMAIN

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for an Arcane config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "environment_count": len(coordinator.data.get("environments", {})),
        "container_count": len(coordinator.data.get("containers", {})),
        "project_count": len(coordinator.data.get("projects", {})),
        "environments": coordinator.data.get("environments", {}),
    }
