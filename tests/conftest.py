"""Shared fixtures."""

from __future__ import annotations

import time
from typing import Any

import pytest

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.bank_feed_alert_for_ynab.const import API_BASE, CONF_PLAN_ID, DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"
PLAN_ID = "11111111-1111-1111-1111-111111111111"
ACCOUNTS_URL = f"{API_BASE}/plans/{PLAN_ID}/accounts"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load this custom integration."""


@pytest.fixture
async def credentials(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN
    )


def account(
    account_id: str,
    name: str,
    *,
    linked: bool = True,
    in_error: bool = False,
    closed: bool = False,
) -> dict[str, Any]:
    return {
        "id": account_id,
        "name": name,
        "type": "checking",
        "on_budget": True,
        "closed": closed,
        "deleted": False,
        "balance": 0,
        "direct_import_linked": linked,
        "direct_import_in_error": in_error,
    }


def accounts_body(*accounts: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"accounts": list(accounts), "server_knowledge": 1}}


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=PLAN_ID,
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "access",
                "refresh_token": "refresh",
                "token_type": "bearer",
                "scope": "read-only",
                "expires_in": 7200,
                "expires_at": time.time() + 7200,
            },
            CONF_PLAN_ID: PLAN_ID,
        },
    )
    entry.add_to_hass(hass)
    return entry
