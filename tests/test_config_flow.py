"""OAuth flow: read-only scope, plan choice, duplicates, reauth, options."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow

from custom_components.bank_feed_alert_for_ynab.const import (
    API_BASE,
    CONF_ESCALATE_AFTER_DAYS,
    CONF_PLAN_ID,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import CLIENT_ID, PLAN_ID

REDIRECT_URL = "https://example.com/auth/external/callback"
TOKEN = {
    "access_token": "mock-access",
    "refresh_token": "mock-refresh",
    "token_type": "bearer",
    "expires_in": 7200,
    "scope": "read-only",
}


async def _authorise(hass, hass_client_no_auth, aioclient_mock, result):
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT_URL}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith(f"{OAUTH2_AUTHORIZE}?response_type=code&client_id={CLIENT_ID}")
    assert "scope=read-only" in result["url"]
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    aioclient_mock.post(OAUTH2_TOKEN, json=TOKEN)


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_single_plan_creates_entry(hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await _authorise(hass, hass_client_no_auth, aioclient_mock, result)
    aioclient_mock.get(f"{API_BASE}/plans", json={"data": {"plans": [{"id": PLAN_ID, "name": "Home"}]}})
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"][CONF_PLAN_ID] == PLAN_ID
    assert result["data"]["token"]["access_token"] == "mock-access"
    assert result["result"].unique_id == PLAN_ID
    # The plans lookup carried the new token.
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer mock-access"


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_several_plans_asks_which(hass: HomeAssistant, hass_client_no_auth, aioclient_mock: AiohttpClientMocker):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await _authorise(hass, hass_client_no_auth, aioclient_mock, result)
    aioclient_mock.get(
        f"{API_BASE}/plans",
        json={"data": {"plans": [{"id": PLAN_ID, "name": "Home"}, {"id": "p2", "name": "Business"}]}},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "plan"
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PLAN_ID: "p2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Business"


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_same_plan_twice_aborts(hass: HomeAssistant, hass_client_no_auth, aioclient_mock, config_entry):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await _authorise(hass, hass_client_no_auth, aioclient_mock, result)
    aioclient_mock.get(f"{API_BASE}/plans", json={"data": {"plans": [{"id": PLAN_ID, "name": "Home"}]}})
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_reauth_updates_token(hass: HomeAssistant, hass_client_no_auth, aioclient_mock, config_entry):
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await _authorise(hass, hass_client_no_auth, aioclient_mock, result)
    aioclient_mock.get(f"{API_BASE}/plans", json={"data": {"plans": [{"id": PLAN_ID, "name": "Home"}]}})
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["token"]["access_token"] == "mock-access"
    assert config_entry.data[CONF_PLAN_ID] == PLAN_ID


@pytest.mark.usefixtures("current_request_with_host", "credentials")
async def test_reauth_with_another_account_is_refused(hass: HomeAssistant, hass_client_no_auth, aioclient_mock, config_entry):
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await _authorise(hass, hass_client_no_auth, aioclient_mock, result)
    aioclient_mock.get(f"{API_BASE}/plans", json={"data": {"plans": [{"id": "someone-else", "name": "Other"}]}})
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data["token"]["access_token"] == "access"


async def test_options_set_escalation(hass: HomeAssistant, config_entry):
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ESCALATE_AFTER_DAYS: 5}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_ESCALATE_AFTER_DAYS] == 5
