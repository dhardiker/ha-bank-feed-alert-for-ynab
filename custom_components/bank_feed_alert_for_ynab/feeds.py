"""Bank-feed health from YNAB account records.

Deliberately free of Home Assistant so it can be tested - and reused - on its own.

YNAB marks an account `direct_import_linked` when it is connected to a bank for
automatic import, and `direct_import_in_error` when that connection is unhealthy
(typically an expired consent that needs the user to reconnect it in YNAB).
YNAB records neither when the error began nor when it was fixed, so we remember
both ourselves: the first poll that saw an error, and the first poll that saw the
account healthy again.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Feed:
    """One linked account's bank connection."""

    account_id: str
    name: str
    in_error: bool
    in_error_since: datetime | None
    """First poll that saw the error (so "at least since"); None while healthy."""
    last_reconnected: datetime | None
    """First poll that saw the account healthy after an error, or when the user said they reconnected it."""

    def expected_lapse(self, lifetime: timedelta | None) -> datetime | None:
        """When the connection should next need reconnecting, if its lifetime and last reconnection are known."""
        if self.in_error or not lifetime or self.last_reconnected is None:
            return None
        return self.last_reconnected + lifetime


@dataclass(frozen=True)
class Snapshot:
    """Every linked account's feed at one poll."""

    feeds: dict[str, Feed]
    checked_at: datetime

    @property
    def broken(self) -> list[Feed]:
        """Feeds in error, by name."""
        return sorted(
            (feed for feed in self.feeds.values() if feed.in_error),
            key=lambda feed: feed.name.casefold(),
        )

    @property
    def broken_since(self) -> datetime | None:
        """When the longest-running current error began."""
        onsets = [feed.in_error_since for feed in self.broken if feed.in_error_since]
        return min(onsets) if onsets else None

    def next_lapse(self, lifetime: timedelta | None) -> datetime | None:
        """The soonest projected lapse among healthy feeds."""
        lapses = [lapse for feed in self.feeds.values() if (lapse := feed.expected_lapse(lifetime))]
        return min(lapses) if lapses else None

    def overdue(self, after: timedelta, now: datetime) -> bool:
        """True once any feed has been in error for `after` or longer."""
        since = self.broken_since
        return since is not None and now - since >= after

    def memory(self) -> dict[str, dict[str, str | None]]:
        """What must survive a restart: per account, the error onset and last reconnection."""
        return {
            feed.account_id: {
                "in_error_since": _iso(feed.in_error_since),
                "last_reconnected": _iso(feed.last_reconnected),
            }
            for feed in self.feeds.values()
        }


def is_linked(account: Mapping[str, Any]) -> bool:
    """An open account with a bank connection - the only kind that can need reconnecting."""
    return (
        bool(account.get("direct_import_linked"))
        and not account.get("closed")
        and not account.get("deleted")
    )


def evaluate(
    accounts: Iterable[Mapping[str, Any]],
    memory: Mapping[str, Mapping[str, Any]] | None,
    now: datetime,
) -> Snapshot:
    """Fold one GET /plans/{plan_id}/accounts answer into the remembered state."""
    memory = memory or {}
    feeds: dict[str, Feed] = {}
    for account in accounts:
        if not is_linked(account):
            continue
        account_id = str(account["id"])
        prior = memory.get(account_id, {})
        since = _parse(prior.get("in_error_since"))
        reconnected = _parse(prior.get("last_reconnected"))
        in_error = bool(account.get("direct_import_in_error"))
        if in_error:
            since = since or now
        else:
            if since is not None:
                reconnected = now
            since = None
        feeds[account_id] = Feed(
            account_id=account_id,
            name=str(account.get("name") or account_id),
            in_error=in_error,
            in_error_since=since,
            last_reconnected=reconnected,
        )
    return Snapshot(feeds=feeds, checked_at=now)


def next_interval(
    snapshot: Snapshot,
    now: datetime,
    *,
    normal: timedelta,
    fast: timedelta,
    lifetime: timedelta | None,
    before: timedelta,
    after: timedelta,
) -> timedelta:
    """How long to wait before asking YNAB again.

    Fast while anything is broken, and from `before` a projected lapse until `after` it;
    otherwise normal, but never sleeping past the start of the next projected window.
    """
    if snapshot.broken:
        return fast
    wake = normal
    for feed in snapshot.feeds.values():
        lapse = feed.expected_lapse(lifetime)
        if lapse is None:
            continue
        start, end = lapse - before, lapse + after
        if start <= now <= end:
            return fast
        if now < start:
            wake = min(wake, max(fast, start - now))
    return wake


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    # Only aware timestamps are ever written; ignore anything else rather than
    # compare naive with aware later.
    return parsed if parsed.tzinfo is not None else None
