#!/usr/bin/env python3
"""Test session queueing behavior"""

import pytest
from pathlib import Path
from db import Database
from datetime import datetime
import tempfile


@pytest.fixture
def db():
    """Create a temporary database for testing"""
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db_path = Path(temp_db.name)
    database = Database(db_path)
    yield database
    # Cleanup
    db_path.unlink(missing_ok=True)


def test_same_domain_queues_properly(db):
    """Test that consecutive unblocks of the same domain queue sequentially"""
    # Create first session
    session1 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Create second session for same domain
    session2 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Get both sessions
    sessions = db.get_pending_sessions()
    assert len(sessions) == 2, "Should have 2 pending sessions"

    s1 = next(s for s in sessions if s['id'] == session1)
    s2 = next(s for s in sessions if s['id'] == session2)

    # Verify session 2 starts after session 1 ends
    assert s2['start_at'] > s1['end_at'], "Session 2 should start after session 1 ends"

    # Verify the gap equals the wait period (1 minute)
    gap_minutes = (s2['start_at'] - s1['end_at']).total_seconds() / 60
    assert abs(gap_minutes - 1.0) < 0.01, f"Gap should be 1 minute, got {gap_minutes}"


def test_different_domains_dont_queue(db):
    """Test that different domains can have overlapping sessions"""
    # Create session for youtube
    session1 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Create session for reddit (different domain)
    session2 = db.create_session(
        profile='test',
        domains=['reddit.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    sessions = db.get_pending_sessions()
    s1 = next(s for s in sessions if s['id'] == session1)
    s2 = next(s for s in sessions if s['id'] == session2)

    # Both should start at roughly the same time (within a few seconds)
    time_diff = abs((s2['start_at'] - s1['start_at']).total_seconds())
    assert time_diff < 5, "Different domains should start at same time, not queue"


def test_overlapping_domains_queue(db):
    """Test that sessions with any overlapping domains queue properly"""
    # Create session for youtube only
    session1 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Create another session for youtube (to extend the queue)
    session2 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Create session with multiple domains, one of which overlaps (youtube)
    session3 = db.create_session(
        profile='test',
        domains=['youtube.com', 'twitter.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    sessions = db.get_pending_sessions()
    s2 = next(s for s in sessions if s['id'] == session2)
    s3 = next(s for s in sessions if s['id'] == session3)

    # Session 3 should start after session 2 ends (because of youtube overlap)
    assert s3['start_at'] > s2['end_at'], "Session with overlapping domain should queue"

    gap_minutes = (s3['start_at'] - s2['end_at']).total_seconds() / 60
    assert abs(gap_minutes - 1.0) < 0.01, f"Gap should be 1 minute, got {gap_minutes}"


def test_multiple_queued_sessions(db):
    """Test that multiple sessions for same domain all queue properly"""
    sessions_created = []

    # Create 3 sessions for the same domain
    for i in range(3):
        session_id = db.create_session(
            profile='test',
            domains=['youtube.com'],
            wait_minutes=1,
            duration_minutes=5
        )
        sessions_created.append(session_id)

    sessions = db.get_pending_sessions()
    assert len(sessions) == 3, "Should have 3 pending sessions"

    # Sort by start time
    sessions.sort(key=lambda s: s['start_at'])

    # Verify each session starts after the previous one ends
    for i in range(len(sessions) - 1):
        current = sessions[i]
        next_session = sessions[i + 1]

        assert next_session['start_at'] > current['end_at'], \
            f"Session {i+1} should start after session {i} ends"

        gap_minutes = (next_session['start_at'] - current['end_at']).total_seconds() / 60
        assert abs(gap_minutes - 1.0) < 0.01, \
            f"Gap between session {i} and {i+1} should be 1 minute, got {gap_minutes}"


def test_independent_unblock_multiple_targets(db):
    """Test that unblocking multiple different domains creates independent sessions

    This simulates: alwaysblock unblock gmail slack facebook
    Each should create a separate session that starts independently,
    NOT queued serially (they have different domains).
    """
    # Create sessions for different domains (as if user ran: unblock gmail slack facebook)
    targets = [
        ['gmail.com'],
        ['slack.com'],
        ['facebook.com']
    ]

    session_ids = []

    for domains in targets:
        session_id = db.create_session(
            profile='test',
            domains=domains,
            wait_minutes=1,
            duration_minutes=5
        )
        session_ids.append(session_id)

    # Get all sessions
    sessions = db.get_pending_sessions()
    assert len(sessions) == 3, "Should have 3 pending sessions"

    # All sessions should start at roughly the same time (within a few seconds)
    # because they are independent (different domains)
    start_times = [s['start_at'] for s in sessions]
    earliest = min(start_times)
    latest = max(start_times)

    time_spread = (latest - earliest).total_seconds()
    assert time_spread < 5, \
        f"Independent domains should start at same time, but spread is {time_spread}s"


def test_same_domain_queues_when_active(db):
    """Test that domain-based queueing works correctly

    Scenario: slack is currently active, user runs 'unblock instagram slack'
    - Instagram should start independently (no overlap, no queue)
    - Slack should queue after the EXISTING slack session
    """
    # Create an active slack session
    slack_session_1 = db.create_session(
        profile='test',
        domains=['slack.com'],
        wait_minutes=0,  # Active immediately
        duration_minutes=30
    )

    # Get the first slack session to know when it ends
    sessions = db.get_active_sessions()
    slack_1 = next(s for s in sessions if s['id'] == slack_session_1)

    # Now simulate: unblock instagram slack
    # Create instagram session (should be independent)
    instagram_session = db.create_session(
        profile='test',
        domains=['instagram.com'],
        wait_minutes=1,
        duration_minutes=30
    )

    # Create second slack session (should queue after first slack)
    slack_session_2 = db.create_session(
        profile='test',
        domains=['slack.com'],
        wait_minutes=1,
        duration_minutes=30
    )

    # Get all sessions
    all_sessions = db.get_pending_sessions() + db.get_active_sessions()
    instagram = next(s for s in all_sessions if s['id'] == instagram_session)
    slack_2 = next(s for s in all_sessions if s['id'] == slack_session_2)

    # Verify: slack_2 should queue after slack_1
    assert slack_2['start_at'] > slack_1['end_at'], \
        "Second slack should queue after first slack"

    # The gap should be the wait time (1 minute)
    gap_from_slack1 = (slack_2['start_at'] - slack_1['end_at']).total_seconds() / 60
    assert abs(gap_from_slack1 - 1.0) < 0.01, \
        f"Slack 2 should start 1 min after slack 1 ends, got {gap_from_slack1} min"

    # Verify: instagram should start independently (not queued)
    # It should start at: now + wait_minutes (1 minute)
    time_from_now = (instagram['start_at'] - datetime.now()).total_seconds() / 60
    assert abs(time_from_now - 1.0) < 0.1, \
        f"Instagram should start in ~1 minute (independent), got {time_from_now} min"
