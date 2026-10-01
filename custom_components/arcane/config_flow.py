from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectOptionDict

from .api import ArcaneAPI, ArcaneAuthError
from .const import (
    CONF_API_KEY,
    CONF_ENV_ID,
    CONF_ENV_NAME,
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): str,
    }
)


async def discover_environments(
    hass: HomeAssistant, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate Arcane Manager credentials and return available environments."""
    session = async_get_clientsession(hass)
    api = ArcaneAPI(data[CONF_HOST], data[CONF_API_KEY], session)

    try:
        response = await api.get_environments()
    except ArcaneAuthError as err:
        raise InvalidAuth from err
    except Exception as err:
        raise CannotConnect from err

    environments = response.get("data", [])
    if not isinstance(environments, list):
        raise CannotConnect

    return [
        environment
        for environment in environments
        if isinstance(environment, dict) and environment.get("id")
    ]


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}
        self._environments: dict[str, dict[str, Any]] = {}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return ArcaneOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                environments = await discover_environments(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if not environments:
                    errors["base"] = "no_environments"
                else:
                    self._connection_data = dict(user_input)
                    self._environments = {
                        str(environment["id"]): environment
                        for environment in environments
                    }
                    return await self.async_step_environment()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_environment(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._connection_data or not self._environments:
            return self.async_abort(reason="setup_expired")

        if user_input is not None:
            environment_id = str(user_input[CONF_ENV_ID])
            environment = self._environments.get(environment_id)
            if environment is None:
                return self.async_abort(reason="environment_unavailable")

            host = self._connection_data[CONF_HOST].rstrip("/").lower()
            await self.async_set_unique_id(f"{host}:{environment_id}")
            self._abort_if_unique_id_configured()

            environment_name = str(environment.get("name") or environment_id)
            return self.async_create_entry(
                title=f"Arcane · {environment_name}",
                data={
                    **self._connection_data,
                    CONF_ENV_ID: environment_id,
                    CONF_ENV_NAME: environment_name,
                },
            )

        options = [
            SelectOptionDict(
                value=environment_id,
                label=str(environment.get("name") or environment_id),
            )
            for environment_id, environment in self._environments.items()
        ]

        return self.async_show_form(
            step_id="environment",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENV_ID): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )


class ArcaneOptionsFlow(config_entries.OptionsFlow):
    """Handle Arcane options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600))
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid authentication."""
