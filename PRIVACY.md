# Privacy

*Last updated: 18 November 2026*

Bank Feed Alert for YNAB runs entirely inside your own Home Assistant. There is no
server, service or account belonging to this project, and the project never sees
your data.

## What it reads

- **Signing in** uses **your own** YNAB OAuth application (created in your YNAB
  Developer Settings) and asks YNAB for **read-only** access. YNAB rejects any write
  made with a read-only token, so the integration cannot change your plan.
- **When it signs in**, it lists your plans (`GET /plans`) once, so you can pick
  the one to watch.
- **Every few hours** (4 by default; every 30 minutes while a connection is broken or about
  to lapse), it reads that plan's accounts (`GET /plans/{plan_id}/accounts`).
  It uses only each account's ID, name, whether it is closed or deleted, and YNAB's
  two bank-connection flags (`direct_import_linked`, `direct_import_in_error`). It
  ignores balances and everything else in the response, and never reads
  transactions.

## What it keeps, and where

- **The OAuth access and refresh tokens:** in the integration's config entry, in
  Home Assistant's own storage, as for any OAuth integration.
- **For each linked account:** its ID, and the times an error was first seen and the
  connection was next seen healthy (or that you marked it reconnected). These are in Home Assistant's storage
  (`.storage/bank_feed_alert_for_ynab.<entry id>`), so an alert keeps its start time
  across restarts.
- **Entities and the repair issue:** account names, as shown in Home Assistant.
  Home Assistant's recorder keeps entity history as it does for any entity.

Your data is not sent to any third party, sold, or used for anything other than
showing the state of your bank connections in your Home Assistant.

## Removing it

- Delete the integration in Home Assistant to remove its stored state, entities and
  repair issue.
- In YNAB's Developer Settings, where you created the OAuth application, revoke its
  access or delete the application.

If this ever changes how data is used, this file will say so, with a new date, and
the release notes will ask you to re-authorise.
