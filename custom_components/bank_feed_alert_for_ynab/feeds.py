"""Bank-feed health from YNAB account records.

Deliberately free of Home Assistant so it can be tested - and reused - on its own.

YNAB marks an account `direct_import_linked` when it is connected to a bank for
automatic import, and `direct_import_in_error` when that connection is unhealthy
(typically an expired consent that needs the user to reconnect it in YNAB).
YNAB records neither when the error began nor when it was fixed, so we remember
both ourselves: the first poll that saw an error, and the first poll that saw the
account healthy again.

Every change is also kept as an event bracketed by two checks - the last that saw
the old state and the first that saw the new one - so that, over a few cycles, the
real lifetime of a bank connection can be learned (is it 90 days to the minute, or
"day 90 at a fixed time"?). Bracket width is the check interval: 30 minutes while
broken or near a projected lapse, a few hours otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

HISTORY_LIMIT = 200
"""Events kept (about 30 years of 90-day cycles for three accounts)."""

BROKE = "broke"
RECONNECTED = "reconnected"
MARKED = "marked"  # the user said they reconnected (early, or before installing)


@dataclass(frozen=True)
class Event:
    """A change in one account's connection, bracketed by the checks either side of it."""

    account_id: str
    name: str
    kind: str
    after: datetime | None
    """Last check that saw the previous state; None if unknown (first ever check, or marked)."""
    by: datetime
    """First check that saw the new state (for MARKED: the time the user gave)."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "kind": self.kind,
            "after": _iso(self.after),
            "by": _iso(self.by),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event | None:
        by = _parse(data.get("by"))
        if by is None or data.get("kind") not in (BROKE, RECONNECTED, MARKED):
            return None
        return cls(
            account_id=str(data.get("account_id")),
            name=str(data.get("name") or data.get("account_id")),
            kind=str(data["kind"]),
            after=_parse(data.get("after")),
            by=by,
        )


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
    history: tuple[Event, ...] = ()
    changes: tuple[Event, ...] = field(default=(), compare=False)
    """The events this snapshot added to the history."""

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

    def memory(self) -> dict[str, Any]:
        """What must survive a restart: per account, the error onset and last reconnection; the history."""
        return {
            "checked_at": _iso(self.checked_at),
            "accounts": {
                feed.account_id: {
                    "in_error_since": _iso(feed.in_error_since),
                    "last_reconnected": _iso(feed.last_reconnected),
                }
                for feed in self.feeds.values()
            },
            "history": [event.as_dict() for event in self.history],
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
    memory: Mapping[str, Any] | None,
    now: datetime,
) -> Snapshot:
    """Fold one GET /plans/{plan_id}/accounts answer into the remembered state."""
    remembered, previous_check, history = _split(memory)
    feeds: dict[str, Feed] = {}
    changes: list[Event] = []
    for account in accounts:
        if not is_linked(account):
            continue
        account_id = str(account["id"])
        name = str(account.get("name") or account_id)
        known = account_id in remembered
        prior = remembered.get(account_id, {})
        since = _parse(prior.get("in_error_since"))
        reconnected = _parse(prior.get("last_reconnected"))
        in_error = bool(account.get("direct_import_in_error"))
        if in_error:
            if since is None:
                changes.append(Event(account_id, name, BROKE, previous_check if known else None, now))
                since = now
        else:
            if since is not None:
                reconnected = now
                changes.append(Event(account_id, name, RECONNECTED, previous_check, now))
            since = None
        feeds[account_id] = Feed(
            account_id=account_id,
            name=name,
            in_error=in_error,
            in_error_since=since,
            last_reconnected=reconnected,
        )
    return Snapshot(
        feeds=feeds,
        checked_at=now,
        history=tuple([*history, *changes][-HISTORY_LIMIT:]),
        changes=tuple(changes),
    )


def mark_reconnected(snapshot: Snapshot, account_ids: Iterable[str], when: datetime) -> Snapshot:
    """The user says these connections were renewed at `when`. Ignored for feeds YNAB says are broken."""
    feeds = dict(snapshot.feeds)
    events: list[Event] = []
    for account_id in account_ids:
        feed = feeds.get(account_id)
        if feed is None or feed.in_error:
            continue
        feeds[account_id] = replace(feed, last_reconnected=when)
        events.append(Event(account_id, feed.name, MARKED, None, when))
    return replace(
        snapshot,
        feeds=feeds,
        history=tuple([*snapshot.history, *events][-HISTORY_LIMIT:]),
        changes=tuple(events),
    )


def cycles(history: Iterable[Event]) -> list[dict[str, Any]]:
    """Each connection's lifetimes: from a reconnection (seen or marked) to the next break.

    The true lifetime lies between `lifetime_min` and `lifetime_max`: the brackets either side.
    A marked start is only as good as the time the user gave (`start` is "marked").
    """
    out: list[dict[str, Any]] = []
    starts: dict[str, Event] = {}
    for event in history:
        if event.kind in (RECONNECTED, MARKED):
            starts[event.account_id] = event
        elif event.kind == BROKE and (start := starts.pop(event.account_id, None)):
            start_earliest = start.after or start.by
            out.append(
                {
                    "account_id": event.account_id,
                    "name": event.name,
                    "start": start.kind,
                    "reconnected_after": _iso(start.after),
                    "reconnected_by": _iso(start.by),
                    "broke_after": _iso(event.after),
                    "broke_by": _iso(event.by),
                    "lifetime_min_hours": _hours(event.after - start.by) if event.after else None,
                    "lifetime_max_hours": _hours(event.by - start_earliest),
                }
            )
    return out


def _split(memory: Mapping[str, Any] | None) -> tuple[Mapping[str, Mapping[str, Any]], datetime | None, list[Event]]:
    """Read either memory layout: {accounts, checked_at, history}, or the first release's bare account map."""
    if not memory:
        return {}, None, []
    if "accounts" not in memory:
        return memory, None, []
    history = [e for raw in memory.get("history") or [] if (e := Event.from_dict(raw))]
    return memory.get("accounts") or {}, _parse(memory.get("checked_at")), history


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 2)


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
