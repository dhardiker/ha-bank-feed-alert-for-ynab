"""Set-up, entities, the repair issue's life cycle, and lost authorisation."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.bank_feed_alert_for_ynab import issue_id
from custom_components.bank_feed_alert_for_ynab.const import DOMAIN, OAUTH2_TOKEN, SCAN_INTERVAL
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import ACCOUNTS_URL, account, accounts_body

NEEDS = "binary_sensor.home_bank_feeds_need_reconnecting"
OVERDUE = "binary_sensor.home_reconnect_overdue"
COUNT = "sensor.home_broken_bank_feeds"
SINCE = "sensor.home_broken_since"
CURRENT = "binary_sensor.home_current_account"


def _serve(aioclient_mock: AiohttpClientMocker, *accounts, status: int = 200) -> None:
    aioclient_mock.clear_requests()
    # Ticking the clock past the 2-hour token life makes the session refresh it first.
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={"access_token": "refreshed", "refresh_token": "refresh-2", "token_type": "bearer", "expires_in": 7200},
    )
    if status == 200:
        aioclient_mock.get(ACCOUNTS_URL, json=accounts_body(*accounts))
    else:
        aioclient_mock.get(ACCOUNTS_URL, status=status, json={"error": {"id": str(status)}})


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, by: timedelta = SCAN_INTERVAL) -> None:
    freezer.tick(by)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("credentials")
async def test_healthy_plan(hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry):
    _serve(aioclient_mock, account("a", "Current account"), account("b", "Wallet", linked=False))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(NEEDS).state == STATE_OFF
    assert hass.states.get(OVERDUE).state == STATE_OFF
    assert hass.states.get(COUNT).state == "0"
    assert hass.states.get(CURRENT).state == STATE_OFF
    assert hass.states.get("binary_sensor.home_wallet") is None  # not linked: not watched
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(config_entry.entry_id)) is None


@pytest.mark.usefixtures("credentials")
async def test_issue_raised_escalated_and_cleared(
    hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    issues = ir.async_get(hass)
    _serve(aioclient_mock, account("a", "Current account", in_error=True), account("c", "Credit card"))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(NEEDS).state == STATE_ON
    assert hass.states.get(NEEDS).attributes["accounts"] == ["Current account"]
    assert hass.states.get(COUNT).state == "1"
    assert hass.states.get(CURRENT).state == STATE_ON
    assert hass.states.get(OVERDUE).state == STATE_OFF
    issue = issues.async_get_issue(DOMAIN, issue_id(config_entry.entry_id))
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "reconnect_needed"
    assert issue.translation_placeholders["accounts"] == "Current account"
    onset = hass.states.get(SINCE).state

    # Three days on, still broken: the alert escalates and the onset has not moved.
    _serve(aioclient_mock, account("a", "Current account", in_error=True), account("c", "Credit card"))
    await _poll(hass, freezer, timedelta(days=3))
    assert hass.states.get(OVERDUE).state == STATE_ON
    assert hass.states.get(SINCE).state == onset
    assert config_entry.data["token"]["access_token"] == "refreshed"
    issue = issues.async_get_issue(DOMAIN, issue_id(config_entry.entry_id))
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_key == "reconnect_overdue"

    # Reconnected: everything clears and the reconnection is recorded.
    _serve(aioclient_mock, account("a", "Current account"), account("c", "Credit card"))
    await _poll(hass, freezer)
    assert hass.states.get(NEEDS).state == STATE_OFF
    assert hass.states.get(OVERDUE).state == STATE_OFF
    assert hass.states.get(CURRENT).attributes["last_reconnected"] is not None
    assert issues.async_get_issue(DOMAIN, issue_id(config_entry.entry_id)) is None


@pytest.mark.usefixtures("credentials")
async def test_onset_survives_a_reload(
    hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    _serve(aioclient_mock, account("a", "Current account", in_error=True))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    onset = hass.states.get(SINCE).state

    freezer.tick(timedelta(days=2))
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SINCE).state == onset
    assert hass.states.get(OVERDUE).state == STATE_OFF

    _serve(aioclient_mock, account("a", "Current account", in_error=True))
    await _poll(hass, freezer, timedelta(days=1))
    assert hass.states.get(OVERDUE).state == STATE_ON


@pytest.mark.usefixtures("credentials")
async def test_new_and_unlinked_accounts(
    hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    _serve(aioclient_mock, account("a", "Current account"))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    _serve(aioclient_mock, account("a", "Current account", linked=False), account("s", "Savings", in_error=True))
    await _poll(hass, freezer)
    assert hass.states.get(CURRENT).state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.home_savings").state == STATE_ON


@pytest.mark.usefixtures("credentials")
async def test_refused_token_starts_reauth(
    hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    _serve(aioclient_mock, account("a", "Current account"))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    _serve(aioclient_mock, status=401)
    await _poll(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" and f["handler"] == DOMAIN for f in flows)


@pytest.mark.usefixtures("credentials")
async def test_outage_retries_setup(hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry):
    _serve(aioclient_mock, status=503)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("credentials")
async def test_removal_clears_issue(hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry):
    _serve(aioclient_mock, account("a", "Current account", in_error=True))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(config_entry.entry_id))
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(config_entry.entry_id)) is None


@pytest.mark.usefixtures("credentials")
async def test_refused_refresh_starts_reauth(
    hass: HomeAssistant, aioclient_mock, config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
):
    _serve(aioclient_mock, account("a", "Current account"))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.post(OAUTH2_TOKEN, status=400, json={"error": "invalid_grant"})
    await _poll(hass, freezer, timedelta(hours=3))
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" and f["handler"] == DOMAIN for f in flows)
