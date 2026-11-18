"""Constants for Bank Feed Alert for YNAB."""

from datetime import timedelta

DOMAIN = "bank_feed_alert_for_ynab"

API_BASE = "https://api.ynab.com/v1"
OAUTH2_AUTHORIZE = "https://app.ynab.com/oauth/authorize"
OAUTH2_TOKEN = "https://app.ynab.com/oauth/token"
# Read-only: the integration only ever reads account records. YNAB answers any
# write made with such a token with 403 Forbidden.
OAUTH2_SCOPE = "read-only"

YNAB_APP_URL = "https://app.ynab.com/"
YNAB_DEVELOPER_SETTINGS_URL = "https://app.ynab.com/settings/developer"
MY_REDIRECT_URL = "https://my.home-assistant.io/redirect/oauth"

CONF_PLAN_ID = "plan_id"
CONF_ESCALATE_AFTER_DAYS = "escalate_after_days"
DEFAULT_ESCALATE_AFTER_DAYS = 3

# One request per poll; YNAB allows 200 an hour per token.
SCAN_INTERVAL = timedelta(minutes=30)

STORAGE_VERSION = 1
