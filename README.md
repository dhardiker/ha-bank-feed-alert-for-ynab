# Bank Feed Alert for YNAB

A Home Assistant integration that tells you when YNAB's bank connections need
reconnecting, before weeks of transactions go missing.

YNAB's Direct Import keeps your accounts in step with the bank, until a connection
stops working. That happens on a schedule in the UK and Europe, where open-banking
consent has to be renewed (often every 90 days). When it happens, YNAB marks the
account in the app, but it doesn't email you. Transactions quietly stop arriving
until you next look.

This integration reads that mark from YNAB's API and tells Home Assistant:

- **A repair** appears under *Settings → Repairs*: "YNAB bank connections need
  reconnecting", listing the accounts. If they are still broken after a few days
  (default 3), it becomes an error. It clears itself once YNAB reports the
  connections healthy.
- **Entities** let you notify, escalate and show it on dashboards however you like.

It asks YNAB for **read-only** access, through **your own** YNAB OAuth application.

## What you get

One device per YNAB plan (named after the plan), with:

| Entity | What it says |
| --- | --- |
| `binary_sensor.<plan>_bank_feeds_need_reconnecting` | On while any linked account's bank connection is in error. Attributes: `accounts` (names) and `broken_since`. |
| `binary_sensor.<plan>_reconnect_overdue` | On once a connection has been broken for the escalation period (option, default 3 days). |
| `binary_sensor.<plan>_<account>` | One per linked account: on when that account needs reconnecting. Attributes: `in_error_since`, `last_reconnected`. Unavailable once the account is closed or unlinked. |
| `sensor.<plan>_broken_bank_feeds` | How many linked accounts are in error. |
| `sensor.<plan>_broken_since` | When the longest-running current error was first seen. |
| `sensor.<plan>_last_checked` | When YNAB last answered (diagnostic): proof the watch itself is working. |

The integration checks YNAB every 30 minutes, one request per check (YNAB allows 200
an hour). YNAB doesn't say when a connection broke, so "since" means the first check
that saw it. It also doesn't say when a connection will expire. `last_reconnected`
records when it came back, if you want to remind yourself before the next renewal.

## Install

**HACS:** *HACS → ⋮ → Custom repositories*. Add
`https://github.com/dhardiker/ha-bank-feed-alert-for-ynab` as an *Integration*, then
install *Bank Feed Alert for YNAB* and restart Home Assistant.

**Manual:** copy `custom_components/bank_feed_alert_for_ynab/` into your
`config/custom_components/` and restart.

Requires Home Assistant 2025.2 or later.

## Set up

1. **Create a YNAB OAuth application.** In YNAB go to *Account Settings → Developer
   Settings* (<https://app.ynab.com/settings/developer>) and click *New Application*.
   - **Name:** anything that doesn't start with "YNAB". YNAB's terms reserve that,
     though "… for YNAB" is fine. For example: *Bank Feed Alert for YNAB (home)*.
   - **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`. If you don't
     use My Home Assistant, use your instance's external URL plus
     `/auth/external/callback`.
   - Leave *Default plan selection* off.

   Applications are private to you, and an application's owner isn't limited by
   YNAB's "restricted mode" for new applications.
2. **Add the integration.** *Settings → Devices & services → Add integration → Bank
   Feed Alert for YNAB*. Enter the application's **Client ID** and **Client Secret**
   when asked; they are stored as Home Assistant *Application Credentials*.
3. **Authorise.** You'll be sent to YNAB to approve **read-only** access. If you have
   more than one plan, pick the one to watch. Add the integration again for another.

**Options:** *Escalate after (days)*, default 3, sets when the repair becomes an error
and `reconnect_overdue` turns on.

If YNAB ever stops accepting the authorisation, Home Assistant asks you to sign in
again; the alert history is kept.

## Example automations

Tell your phone as soon as something breaks:

```yaml
automation:
  - alias: "YNAB bank connections need reconnecting"
    triggers:
      - trigger: state
        entity_id: binary_sensor.home_bank_feeds_need_reconnecting
        to: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "YNAB bank connections need reconnecting"
          message: >-
            {{ state_attr('binary_sensor.home_bank_feeds_need_reconnecting', 'accounts') | join(', ') }}
            stopped importing. Reconnect them in YNAB → Manage Bank Connections.
          data:
            url: "https://app.ynab.com/"
```

Escalate when it's been left too long, for example a time-sensitive notification, a
wall-panel warning, or both:

```yaml
  - alias: "YNAB reconnect overdue"
    triggers:
      - trigger: state
        entity_id: binary_sensor.home_reconnect_overdue
        to: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "🚨 YNAB bank connections still need reconnecting"
          message: >-
            Broken since {{ as_local(as_datetime(states('sensor.home_broken_since'))).strftime('%a %d %b') }}.
            Transactions are not reaching YNAB.
          data:
            push:
              interruption-level: time-sensitive
```

Entity IDs follow your plan's name. The examples assume a plan called *Home*.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

`feeds.py` is the core: deciding which connections are broken, since when, and when
an alert is overdue. It doesn't depend on Home Assistant, so it can be tested and
reused on its own.

## Privacy

Everything stays in your Home Assistant, and there is no service behind this project.
See [PRIVACY.md](PRIVACY.md) for exactly what is read and kept.

## Licence

MIT. See [LICENSE](LICENSE).

---

We are not affiliated, associated, or in any way officially connected with YNAB or
any of its subsidiaries or affiliates. The official YNAB website can be found at
https://www.ynab.com. The names YNAB and You Need A Budget, as well as related names,
tradenames, marks, trademarks, emblems, and images are registered trademarks of YNAB.
