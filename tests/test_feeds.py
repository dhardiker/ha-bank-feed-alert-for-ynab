"""The Home-Assistant-free core: onsets, recovery, escalation, memory."""

from datetime import UTC, datetime, timedelta

from custom_components.bank_feed_alert_for_ynab.feeds import evaluate, is_linked, next_interval

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


NORMAL, FAST = timedelta(hours=4), timedelta(minutes=30)
LIFE = timedelta(days=90)
WIN = {"normal": NORMAL, "fast": FAST, "lifetime": LIFE, "before": timedelta(days=2), "after": timedelta(days=1)}


def _reconnected_at(when):
    broken = evaluate([acct("a", "Current", in_error=True)], {}, when - timedelta(hours=1))
    return evaluate([acct("a", "Current")], broken.memory(), when)


def test_expected_lapse_follows_the_last_reconnection():
    snap = _reconnected_at(T0)
    assert snap.feeds["a"].expected_lapse(LIFE) == T0 + LIFE
    assert snap.next_lapse(LIFE) == T0 + LIFE
    assert snap.feeds["a"].expected_lapse(None) is None  # projection switched off
    never = evaluate([acct("b", "Savings")], {}, T0)
    assert never.next_lapse(LIFE) is None  # no reconnection seen: nothing to project


def test_interval_is_normal_far_from_a_lapse_and_fast_when_broken():
    snap = _reconnected_at(T0)
    assert next_interval(snap, T0 + timedelta(days=10), **WIN) == NORMAL
    broken = evaluate([acct("a", "Current", in_error=True)], snap.memory(), T0 + timedelta(days=10))
    assert next_interval(broken, T0 + timedelta(days=10), **WIN) == FAST


def test_interval_is_fast_from_two_days_before_to_one_day_after_a_projected_lapse():
    snap = _reconnected_at(T0)
    lapse = T0 + LIFE
    assert next_interval(snap, lapse - timedelta(days=2), **WIN) == FAST
    assert next_interval(snap, lapse, **WIN) == FAST
    assert next_interval(snap, lapse + timedelta(days=1), **WIN) == FAST
    # Still healthy a day after: the projection was wrong; back to normal.
    assert next_interval(snap, lapse + timedelta(days=1, minutes=1), **WIN) == NORMAL


def test_interval_never_sleeps_past_the_start_of_a_window():
    snap = _reconnected_at(T0)
    start = T0 + LIFE - timedelta(days=2)
    assert next_interval(snap, start - timedelta(hours=1), **WIN) == timedelta(hours=1)
    assert next_interval(snap, start - timedelta(minutes=5), **WIN) == FAST  # never below fast
    assert next_interval(snap, start - timedelta(hours=1), **{**WIN, "lifetime": None}) == NORMAL


def test_history_brackets_each_change_between_two_checks():
    from custom_components.bank_feed_alert_for_ynab.feeds import BROKE, RECONNECTED, cycles

    t1, t2, t3, t4 = (T0 + timedelta(hours=h) for h in (0, 4, 4.5, 5))
    s1 = evaluate([acct("a", "Current")], {}, t1)
    assert s1.history == () and s1.changes == ()
    s2 = evaluate([acct("a", "Current", in_error=True)], s1.memory(), t2)
    assert [(e.kind, e.after, e.by) for e in s2.changes] == [(BROKE, t1, t2)]
    s3 = evaluate([acct("a", "Current", in_error=True)], s2.memory(), t3)
    assert s3.changes == ()
    s4 = evaluate([acct("a", "Current")], s3.memory(), t4)
    assert [(e.kind, e.after, e.by) for e in s4.changes] == [(RECONNECTED, t3, t4)]
    assert [e.kind for e in s4.history] == [BROKE, RECONNECTED]

    # 90 days on it breaks again, between two half-hourly checks: one complete cycle.
    t5 = t4 + timedelta(days=90)
    t6 = t5 + timedelta(minutes=30)
    s5 = evaluate([acct("a", "Current")], s4.memory(), t5)
    s6 = evaluate([acct("a", "Current", in_error=True)], s5.memory(), t6)
    (cycle,) = cycles(s6.history)
    assert cycle["start"] == RECONNECTED
    assert cycle["lifetime_min_hours"] == round((t5 - t4).total_seconds() / 3600, 2)
    assert cycle["lifetime_max_hours"] == round((t6 - t3).total_seconds() / 3600, 2)


def test_first_check_already_broken_has_no_lower_bracket():
    snap = evaluate([acct("a", "Current", in_error=True)], {}, T0)
    (event,) = snap.changes
    assert event.after is None and event.by == T0


def test_marked_reconnection_starts_a_cycle_and_is_recorded():
    from custom_components.bank_feed_alert_for_ynab.feeds import MARKED, cycles, mark_reconnected

    snap = evaluate([acct("a", "Current"), acct("b", "Savings", in_error=True)], {}, T0)
    marked = mark_reconnected(snap, ["a", "b"], T0 - timedelta(days=2))
    assert [(e.kind, e.account_id) for e in marked.changes] == [(MARKED, "a")]  # b is broken: ignored
    assert marked.feeds["a"].last_reconnected == T0 - timedelta(days=2)
    later = evaluate([acct("a", "Current", in_error=True), acct("b", "Savings", in_error=True)],
                     marked.memory(), T0 + timedelta(days=88))
    (cycle,) = cycles(later.history)
    assert cycle["start"] == MARKED and cycle["lifetime_max_hours"] == 90 * 24


def test_history_is_capped_and_first_release_memory_still_loads():
    from custom_components.bank_feed_alert_for_ynab.feeds import HISTORY_LIMIT

    legacy = {"a": {"in_error_since": None, "last_reconnected": T0.isoformat()}}
    snap = evaluate([acct("a", "Current")], legacy, T0 + timedelta(days=1))
    assert snap.feeds["a"].last_reconnected == T0
    memory = snap.memory()
    for i in range(HISTORY_LIMIT + 10):
        memory = evaluate([acct("a", "Current", in_error=bool(i % 2 == 0))], memory,
                          T0 + timedelta(days=2, hours=i)).memory()
    assert len(memory["history"]) == HISTORY_LIMIT
