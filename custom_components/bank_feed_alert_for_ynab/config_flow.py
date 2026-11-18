"""Config flow: OAuth (read-only) with the user's own YNAB OAuth application, then pick a plan."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE,
    CHECK_INTERVAL_HOURS_RANGE,
    CONF_CHECK_INTERVAL_HOURS,
    CONF_CONNECTION_LIFETIME_DAYS,
    CONF_ESCALATE_AFTER_DAYS,
    CONF_PLAN_ID,
    CONNECTION_LIFETIME_DAYS_RANGE,
    DEFAULT_CHECK_INTERVAL_HOURS,
    DEFAULT_CONNECTION_LIFETIME_DAYS,
    DEFAULT_ESCALATE_AFTER_DAYS,
    DOMAIN,
    ESCALATE_AFTER_DAYS_RANGE,
    OAUTH2_SCOPE,
)

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Authorise with YNAB, then choose which plan to watch."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._oauth_data: dict[str, Any] = {}
        self._plans: dict[str, str] = {}

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Ask YNAB for a read-only token: the integration never writes."""
        return {"scope": OAUTH2_SCOPE}

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Authorised: find the plans this token can read."""
        self._oauth_data = data
        try:
            plans = await self._async_fetch_plans(data["token"]["access_token"])
        except ClientError:
            return self.async_abort(reason="cannot_connect")
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if entry.data[CONF_PLAN_ID] not in plans:
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data_updates=data)
        if not plans:
            return self.async_abort(reason="no_plans")
        self._plans = plans
        if len(plans) == 1:
            return await self._async_create(next(iter(plans)))
        return await self.async_step_plan()

    async def async_step_plan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """More than one plan: let the user choose."""
        if user_input is not None:
            return await self._async_create(user_input[CONF_PLAN_ID])
        return self.async_show_form(
            step_id="plan",
            data_schema=vol.Schema({vol.Required(CONF_PLAN_ID): vol.In(self._plans)}),
        )

    async def _async_create(self, plan_id: str) -> ConfigFlowResult:
        await self.async_set_unique_id(plan_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._plans[plan_id],
            data={**self._oauth_data, CONF_PLAN_ID: plan_id},
        )

    async def _async_fetch_plans(self, access_token: str) -> dict[str, str]:
        session = async_get_clientsession(self.hass)
        async with session.get(
            f"{API_BASE}/plans", headers={"Authorization": f"Bearer {access_token}"}
        ) as response:
            response.raise_for_status()
            body = await response.json()
        return {plan["id"]: plan["name"] for plan in body["data"]["plans"]}

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """YNAB stopped accepting the authorisation."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Explain, then send the user back through YNAB."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Escalation, check interval and connection lifetime - each bounded."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options

        def bounded(key: str, default: int, bounds: tuple[int, int]) -> tuple[vol.Required, Any]:
            return (
                vol.Required(key, default=options.get(key, default)),
                vol.All(vol.Coerce(int), vol.Range(min=bounds[0], max=bounds[1])),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                dict(
                    [
                        bounded(CONF_ESCALATE_AFTER_DAYS, DEFAULT_ESCALATE_AFTER_DAYS, ESCALATE_AFTER_DAYS_RANGE),
                        bounded(CONF_CHECK_INTERVAL_HOURS, DEFAULT_CHECK_INTERVAL_HOURS, CHECK_INTERVAL_HOURS_RANGE),
                        bounded(
                            CONF_CONNECTION_LIFETIME_DAYS,
                            DEFAULT_CONNECTION_LIFETIME_DAYS,
                            CONNECTION_LIFETIME_DAYS_RANGE,
                        ),
                    ]
                )
            ),
        )
