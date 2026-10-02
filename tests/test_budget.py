#!/usr/bin/env python3
"""Daily budgets: domains.<name>.daily_limit caps session minutes per local day."""
from datetime import datetime, timedelta

import pytest
import yaml

from db import Database, local_midnight


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _set_times(db, session_id, start_ago, end_ago, status='completed'):
    """Rewrite a session's start/end as minutes in the past."""
    now = datetime.now()
    with db._get_conn() as conn:
        conn.execute("UPDATE sessions SET status=?, start_at=?, end_at=? WHERE id=?",
                     (status, db._datetime_to_str(now - timedelta(minutes=start_ago)),
                      db._datetime_to_str(now - timedelta(minutes=end_ago)), session_id))
        conn.commit()


def _minutes(td):
    return round(td.total_seconds() / 60)


def test_nothing_used_without_sessions(db):
    assert db.budget_used('instagram.com') == timedelta()


def test_active_and_pending_sessions_count_in_full(db):
    db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    db.create_session('unblock', ['facebook.com'], 5, 20, target_name='facebook')
    assert _minutes(db.budget_used('instagram.com')) == 30
    assert _minutes(db.budget_used('facebook')) == 20


def test_queued_session_counts_its_duration(db):
    db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    db.create_session('unblock', ['instagram.com'], 5, 30, target_name='instagram.com')
    assert db.get_waiting_sessions()
    assert _minutes(db.budget_used('instagram.com')) == 60


def test_cancelling_refunds_unused_time(db):
    sid = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    _set_times(db, sid, start_ago=5, end_ago=-25, status='active')
    db.cancel_session(sid)
    assert _minutes(db.budget_used('instagram.com')) == 5


def test_cancelled_unstarted_session_is_free(db):
    sid = db.create_session('unblock', ['instagram.com'], 5, 30, target_name='instagram.com')
    db.cancel_session(sid)
    assert db.budget_used('instagram.com') == timedelta()


def test_until_leaves_out_booked_time(db):
    active = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    _set_times(db, active, start_ago=5, end_ago=-25, status='active')
    db.create_session('unblock', ['instagram.com'], 5, 30, target_name='instagram.com')
    assert _minutes(db.budget_used('instagram.com')) == 60
    assert _minutes(db.budget_used('instagram.com', until=datetime.now())) == 5


def test_yesterday_does_not_count_and_midnight_clips(db):
    old = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    span = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    midnight = local_midnight()
    with db._get_conn() as conn:
        for sid, start, end in [(old, -120, -90), (span, -10, 20)]:
            conn.execute("UPDATE sessions SET status='completed', start_at=?, end_at=? WHERE id=?",
                         (db._datetime_to_str(midnight + timedelta(minutes=start)),
                          db._datetime_to_str(midnight + timedelta(minutes=end)), sid))
        conn.commit()
    assert _minutes(db.budget_used('instagram.com')) == 20


def test_exempt_profiles_are_free(db):
    db.create_session('bypass', ['instagram.com'], 0, 5, target_name='instagram.com')
    db.create_session('unblock', ['instagram.com'], 0, 10, target_name='instagram.com', independent=True)
    assert _minutes(db.budget_used('instagram.com', ['bypass'])) == 10
    assert _minutes(db.budget_used('instagram.com')) == 15


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """An AlwaysBlock on a temp HOME with a budgeted instagram."""
    (tmp_path / ".config" / "alwaysblock").mkdir(parents=True)
    (tmp_path / ".local" / "share" / "alwaysblock").mkdir(parents=True)
    config = {
        "default_profile": "unblock",
        "domains": {
            "instagram.com": {"daily_limit": 45},
            "reddit.com": {},
        },
        "profiles": {
            "unblock": {"wait": 0, "duration": 30},
            "quick": {"wait": 0, "duration": 1, "target_type": "all"},
            "bypass": {"wait": 0, "duration": 5, "target_type": "all", "ignore_budget": True},
        },
    }
    with open(tmp_path / ".config" / "alwaysblock" / "config.yaml", "w") as f:
        yaml.dump(config, f)
    monkeypatch.setenv("HOME", str(tmp_path))
    from alwaysblock import AlwaysBlock
    ab = AlwaysBlock()
    ab.json_path = tmp_path / "state.json"
    return ab


def _last_session(brain):
    return max(brain.db.get_active_sessions(), key=lambda s: s['id'])


def test_config_helpers(brain):
    cm = brain.config_manager
    assert cm.budgeted_targets() == ['instagram.com']
    assert cm.profile_ignores_budget('bypass') is True
    assert cm.profile_ignores_budget('unblock') is False


def test_session_is_shortened_to_remaining_budget(brain):
    brain.unblock(['instagram'])
    _set_times(brain.db, _last_session(brain)['id'], start_ago=30, end_ago=0)
    assert brain._budget_left('instagram.com') == 15
    brain.unblock(['instagram'])
    assert _last_session(brain)['duration_minutes'] == 15


def test_spent_target_is_refused(brain):
    brain.unblock(['instagram'])
    sid = _last_session(brain)['id']
    _set_times(brain.db, sid, start_ago=45, end_ago=0)
    assert brain._budget_left('instagram.com') == 0
    with pytest.raises(SystemExit):
        brain.unblock(['instagram'])


def test_all_domains_profile_skips_spent_targets_unless_it_ignores_budget(brain):
    brain.unblock(['instagram'])
    _set_times(brain.db, _last_session(brain)['id'], start_ago=45, end_ago=0)

    brain.unblock([], 'quick')
    assert _last_session(brain)['domains'] == ['reddit.com']

    brain.unblock([], 'bypass')
    assert set(_last_session(brain)['domains']) == {'instagram.com', 'reddit.com'}
