"""Config flow for Novya."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NovyaApiClient, NovyaApiError, NovyaAuthError
from .const import (
    CONF_BASE_URL,
    CONF_EMAIL,
    CONF_EXPLORATION,
    CONF_GENRES,
    CONF_MOOD,
    CONF_PASSWORD,
    CONF_TARGET,
    DEFAULT_BASE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class NovyaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Novya configuration flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return NovyaOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (email + password login)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL).strip()

            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = NovyaApiClient(
                session, base_url, email, user_input[CONF_PASSWORD]
            )
            try:
                await api.async_login()
            except NovyaAuthError:
                errors["base"] = "invalid_auth"
            except NovyaApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Novya login")
                errors["base"] = "unknown"
            else:
                display = (api.user or {}).get("displayName") or email
                return self.async_create_entry(
                    title=f"Novya.live ({display})",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )


class NovyaOptionsFlow(OptionsFlow):
    """Handle Novya options (radio playback target & defaults).

    Note: ``self.config_entry`` is provided by Home Assistant. Do not set it
    explicitly in ``__init__`` (deprecated since HA 2025.12).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Drop empty optional values so defaults apply cleanly.
            cleaned = {k: v for k, v in user_input.items() if v not in (None, "", [])}
            return self.async_create_entry(title="", data=cleaned)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARGET,
                    description={"suggested_value": options.get(CONF_TARGET)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    CONF_GENRES,
                    description={"suggested_value": options.get(CONF_GENRES)},
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_MOOD,
                    description={"suggested_value": options.get(CONF_MOOD)},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_EXPLORATION,
                    default=options.get(CONF_EXPLORATION, 1),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=5, step=0.5, mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
