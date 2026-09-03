#!/usr/bin/env python3
"""Cooldowns count from the END of the last session, for profiles and targets."""
import json
from datetime import datetime, timedelta

import pytest
import yaml

from db import Database
from config_manager import ConfigManager


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _finish(db, session_id, minutes_ago):
    """Mark a session completed with end_at a given number of minutes in the past."""
    end = datetime.now() - timedelta(minutes=minutes_ago)
    with db._get_conn() as conn:
        conn.execute("UPDATE sessions SET status='completed', end_at=? WHERE id=?",
                     (db._datetime_to_str(end), session_id))
        conn.commit()


def test_no_history_means_no_cooldown(db):
    assert db.cooldown_remaining(15, profile='bypass') is None
    assert db.cooldown_remaining(15, target_name='instagram.com') is None


def test_zero_cooldown_is_always_clear(db):
    db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    assert db.cooldown_remaining(0, target_name='instagram.com') is None


def test_active_session_counts_until_it_ends(db):
    db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    remaining = db.cooldown_remaining(15, target_name='instagram.com')
    # 30 min session + 15 min cooldown, measured from now
    assert remaining is not None
    assert 44 * 60 < remaining.total_seconds() <= 45 * 60


def test_cooldown_runs_from_session_end(db):
    sid = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    _finish(db, sid, minutes_ago=10)
    remaining = db.cooldown_remaining(15, target_name='instagram.com')
    assert remaining is not None and 4 * 60 < remaining.total_seconds() <= 5 * 60

    _finish(db, sid, minutes_ago=16)
    assert db.cooldown_remaining(15, target_name='instagram.com') is None


def test_profile_and_target_keys_are_independent(db):
    sid = db.create_session('peek', ['instagram.com'], 0, 1, target_name='instagram.com')
    _finish(db, sid, minutes_ago=2)
    assert db.cooldown_remaining(10, profile='peek') is not None
    assert db.cooldown_remaining(10, profile='unblock') is None
    assert db.cooldown_remaining(10, target_name='instagram.com') is not None
    assert db.cooldown_remaining(10, target_name='facebook') is None


def test_cancelling_active_session_starts_cooldown_now(db):
    sid = db.create_session('unblock', ['instagram.com'], 0, 30, target_name='instagram.com')
    assert db.cancel_session(sid)
    remaining = db.cooldown_remaining(15, target_name='instagram.com')
    assert remaining is not None and 14 * 60 < remaining.total_seconds() <= 15 * 60


def test_cancelling_unstarted_session_leaves_no_cooldown(db):
    sid = db.create_session('unblock', ['instagram.com'], 5, 30, target_name='instagram.com')
    assert db.get_pending_sessions()[0]['id'] == sid
    assert db.cancel_session(sid)
    assert db.cooldown_remaining(15, target_name='instagram.com') is None


@pytest.fixture
def cm(tmp_path):
    config = {
        'domains': {
            'instagram.com': {'tags': ['social'], 'cooldown': 15},
            'facebook': {'domains': ['facebook.com', 'messenger.com'], 'cooldown': 15},
            'reddit.com': {'tags': ['social']},
            'hn': {'domains': ['news.ycombinator.com']},
        },
        'profiles': {'unblock': {'wait': 5, 'duration': 30}},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    cm = ConfigManager(str(path))
    cm.load()
    return cm


def test_canonical_target_accepts_shorthand(cm):
    assert cm.canonical_target('instagram') == 'instagram.com'
    assert cm.canonical_target('instagram.com') == 'instagram.com'
    assert cm.canonical_target('facebook') == 'facebook'
    assert cm.canonical_target('hn') == 'hn'
    assert cm.canonical_target('tiktok') is None


def test_resolve_domains_still_expands_groups(cm):
    resolved, invalid = cm.resolve_domains(['facebook', 'reddit', 'nope'])
    assert set(resolved) == {'facebook.com', 'messenger.com', 'reddit.com'}
    assert invalid == ['nope']


def test_target_cooldown_from_config(cm):
    assert cm.get_target_cooldown('instagram.com') == 15
    assert cm.get_target_cooldown('facebook') == 15
    assert cm.get_target_cooldown('reddit.com') == 0
    assert cm.get_target_cooldown('missing') == 0
