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

# Options, each bounded so nobody can set the integration to hammer YNAB.
CONF_ESCALATE_AFTER_DAYS = "escalate_after_days"
DEFAULT_ESCALATE_AFTER_DAYS = 3
ESCALATE_AFTER_DAYS_RANGE = (0, 30)  # 0: escalate as soon as a feed breaks

CONF_CHECK_INTERVAL_HOURS = "check_interval_hours"
DEFAULT_CHECK_INTERVAL_HOURS = 4
CHECK_INTERVAL_HOURS_RANGE = (1, 24)

CONF_CONNECTION_LIFETIME_DAYS = "connection_lifetime_days"
DEFAULT_CONNECTION_LIFETIME_DAYS = 90  # UK/EU open-banking consents
CONNECTION_LIFETIME_DAYS_RANGE = (0, 365)  # 0: don't project lapses

# Fixed: the fast rate, used while a feed is broken and around a projected lapse.
# One request per check; YNAB allows 200 an hour per token.
FAST_INTERVAL = timedelta(minutes=30)
WINDOW_BEFORE_LAPSE = timedelta(days=2)
WINDOW_AFTER_LAPSE = timedelta(days=1)

SERVICE_MARK_RECONNECTED = "mark_reconnected"
EVENT_CONNECTION_CHANGED = f"{DOMAIN}_connection_changed"

STORAGE_VERSION = 1
