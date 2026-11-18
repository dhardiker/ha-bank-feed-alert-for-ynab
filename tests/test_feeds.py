"""The Home-Assistant-free core: onsets, recovery, escalation, memory."""

from datetime import UTC, datetime, timedelta

from custom_components.bank_feed_alert_for_ynab.feeds import evaluate, is_linked

T0 = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def acct(aid, name, *, linked=True, in_error=False, closed=False, deleted=False):
    return {
        "id": aid, "name": name, "closed": closed, "deleted": deleted,
        "direct_import_linked": linked, "direct_import_in_error": in_error,
    }


def test_only_open_linked_accounts_count():
    assert is_linked(acct("a", "A"))
    assert not is_linked(acct("a", "A", linked=False))
    assert not is_linked(acct("a", "A", closed=True))
    assert not is_linked(acct("a", "A", deleted=True))
    snap = evaluate(
        [acct("a", "A"), acct("b", "Cash", linked=False), acct("c", "Old", closed=True, in_error=True)], {}, T0
    )
    assert list(snap.feeds) == ["a"]
    assert snap.broken == []


def test_onset_is_first_poll_that_sees_the_error_and_survives_restarts():
    first = evaluate([acct("a", "Current", in_error=True)], {}, T0)
    assert first.feeds["a"].in_error_since == T0
    # A later poll, from remembered state only (as after a restart): the onset holds.
    later = evaluate([acct("a", "Current", in_error=True)], first.memory(), T0 + timedelta(days=2))
    assert later.feeds["a"].in_error_since == T0
    assert later.broken_since == T0


def test_recovery_clears_onset_and_records_reconnection():
    broken = evaluate([acct("a", "Current", in_error=True)], {}, T0)
    fixed_at = T0 + timedelta(days=1)
    fixed = evaluate([acct("a", "Current")], broken.memory(), fixed_at)
    assert fixed.broken == []
    assert fixed.feeds["a"].in_error_since is None
    assert fixed.feeds["a"].last_reconnected == fixed_at
    # Healthy and staying healthy keeps the reconnection time.
    still = evaluate([acct("a", "Current")], fixed.memory(), fixed_at + timedelta(days=1))
    assert still.feeds["a"].last_reconnected == fixed_at


def test_overdue_uses_the_oldest_current_error():
    memory = evaluate([acct("a", "Current", in_error=True)], {}, T0).memory()
    snap = evaluate(
        [acct("a", "Current", in_error=True), acct("b", "Savings", in_error=True)],
        memory,
        T0 + timedelta(days=2),
    )
    assert [f.name for f in snap.broken] == ["Current", "Savings"]
    assert snap.broken_since == T0
    assert not snap.overdue(timedelta(days=3), T0 + timedelta(days=2, hours=23))
    assert snap.overdue(timedelta(days=3), T0 + timedelta(days=3))


def test_bad_memory_is_ignored_not_fatal():
    snap = evaluate(
        [acct("a", "Current", in_error=True)],
        {"a": {"in_error_since": "not a date", "last_reconnected": "2026-11-01T00:00:00"}},
        T0,
    )
    assert snap.feeds["a"].in_error_since == T0  # unparseable -> treated as new
    assert snap.feeds["a"].last_reconnected is None  # naive timestamps are never written; ignored
