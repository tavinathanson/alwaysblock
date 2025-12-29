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
    """Test that consecutive unblocks of the same domain queue using waiting_for_domain status"""
    # Create first session
    session1 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # First session should be pending (domain is free)
    pending_sessions = db.get_pending_sessions()
    assert len(pending_sessions) == 1, "First session should be pending"
    s1 = pending_sessions[0]

    # Create second session for same domain (should be waiting_for_domain)
    session2 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Second session should be waiting (domain is in use)
    waiting_sessions = db.get_waiting_sessions()
    assert len(waiting_sessions) == 1, "Second session should be waiting_for_domain"
    s2 = waiting_sessions[0]
    assert s2['id'] == session2, "Waiting session should be session 2"
    assert s2['start_at'] is None, "Waiting session should not have start_at yet"
    assert s2['end_at'] is None, "Waiting session should not have end_at yet"


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
    """Test that only exact same domain sets queue, overlapping but different sets are concurrent"""
    # Create session for youtube only
    session1 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # First session should be pending
    assert len(db.get_pending_sessions()) == 1, "First session should be pending"

    # Create another session for youtube (exact same - should queue)
    session2 = db.create_session(
        profile='test',
        domains=['youtube.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Create session with multiple domains, one of which overlaps (youtube)
    # This should NOT queue because it's a different set of domains
    session3 = db.create_session(
        profile='test',
        domains=['youtube.com', 'twitter.com'],
        wait_minutes=1,
        duration_minutes=5
    )

    # Only session2 should be waiting (exact match)
    # Session3 should be pending (different set, allowed concurrently)
    waiting_sessions = db.get_waiting_sessions()
    assert len(waiting_sessions) == 1, "Only session 2 should be waiting_for_domain"
    assert waiting_sessions[0]['id'] == session2, "Session 2 should be waiting"

    # Session 3 should be pending (different domain set, allowed concurrently)
    pending_sessions = db.get_pending_sessions()
    pending_ids = [s['id'] for s in pending_sessions]
    assert session3 in pending_ids, "Session 3 should be pending (different domain set)"


def test_multiple_queued_sessions(db):
    """Test that multiple sessions for same domain use waiting_for_domain"""
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

    # First session should be pending, others should be waiting
    pending_sessions = db.get_pending_sessions()
    waiting_sessions = db.get_waiting_sessions()

    assert len(pending_sessions) == 1, "Should have 1 pending session (first one)"
    assert len(waiting_sessions) == 2, "Should have 2 waiting sessions (second and third)"

    # Verify first session is the first one created
    assert pending_sessions[0]['id'] == sessions_created[0], "First session should be pending"

    # Verify waiting sessions are the second and third
    waiting_ids = [s['id'] for s in waiting_sessions]
    assert sessions_created[1] in waiting_ids, "Second session should be waiting"
    assert sessions_created[2] in waiting_ids, "Third session should be waiting"


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
    """Test that domain-based queueing works correctly with waiting_for_domain

    Scenario: slack is currently active, user runs 'unblock instagram slack'
    - Instagram should start independently (no overlap, no queue)
    - Slack should be waiting_for_domain (slack is in use)
    """
    # Create an active slack session
    slack_session_1 = db.create_session(
        profile='test',
        domains=['slack.com'],
        wait_minutes=0,  # Active immediately
        duration_minutes=30
    )

    # Get the first slack session
    active_sessions = db.get_active_sessions()
    assert len(active_sessions) == 1, "Should have 1 active session"
    slack_1 = active_sessions[0]

    # Now simulate: unblock instagram slack
    # Create instagram session (should be pending - different domain)
    instagram_session = db.create_session(
        profile='test',
        domains=['instagram.com'],
        wait_minutes=1,
        duration_minutes=30
    )

    # Create second slack session (should be waiting - slack is in use)
    slack_session_2 = db.create_session(
        profile='test',
        domains=['slack.com'],
        wait_minutes=1,
        duration_minutes=30
    )

    # Verify: instagram should be pending (independent domain)
    pending_sessions = db.get_pending_sessions()
    assert len(pending_sessions) == 1, "Instagram should be pending"
    instagram = pending_sessions[0]
    assert instagram['id'] == instagram_session, "Pending session should be instagram"

    # Verify: slack_2 should be waiting (slack domain is in use)
    waiting_sessions = db.get_waiting_sessions()
    assert len(waiting_sessions) == 1, "Slack 2 should be waiting_for_domain"
    slack_2 = waiting_sessions[0]
    assert slack_2['id'] == slack_session_2, "Waiting session should be slack 2"
    assert slack_2['start_at'] is None, "Waiting session should not have start_at yet"
    assert slack_2['end_at'] is None, "Waiting session should not have end_at yet"


def test_independent_session_never_queues(db):
    """Test that sessions marked as independent never queue behind other sessions"""
    # Create an "all domains" session
    all_domains = ['youtube.com', 'reddit.com', 'instagram.com']
    session1 = db.create_session(
        profile='unblock',
        domains=all_domains,
        wait_minutes=1,
        duration_minutes=30
    )

    # First session should be pending
    pending = db.get_pending_sessions()
    assert len(pending) == 1, "First session should be pending"

    # Create an independent session with same domains (e.g., bypass)
    # This should NOT queue, even though domains match exactly
    session2 = db.create_session(
        profile='bypass',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=5,
        independent=True  # This is the key flag
    )

    # Independent session should be active immediately (wait=0), not waiting
    active = db.get_active_sessions()
    waiting = db.get_waiting_sessions()
    pending = db.get_pending_sessions()

    assert len(active) == 1, "Independent session should be active"
    assert active[0]['id'] == session2, "Active session should be the independent one"
    assert len(waiting) == 0, "No sessions should be waiting"
    assert len(pending) == 1, "Original session should still be pending"


def test_independent_session_runs_concurrently(db):
    """Test that independent sessions run concurrently with regular sessions"""
    # Create an active session for instagram
    instagram_session = db.create_session(
        profile='unblock',
        domains=['instagram.com'],
        wait_minutes=0,  # Active immediately
        duration_minutes=30
    )

    # Instagram should be active
    active = db.get_active_sessions()
    assert len(active) == 1, "Instagram should be active"

    # Create an independent "bypass" session for all domains (including instagram)
    all_domains = ['youtube.com', 'instagram.com', 'reddit.com']
    bypass_session = db.create_session(
        profile='bypass',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=5,
        independent=True
    )

    # Both sessions should be active
    active = db.get_active_sessions()
    assert len(active) == 2, "Both sessions should be active concurrently"

    # All domains from both sessions should be in the unblocked list
    all_unblocked = set(db.get_all_domains_from_sessions())
    expected = {'youtube.com', 'instagram.com', 'reddit.com'}
    assert all_unblocked == expected, "Union of all active sessions' domains should be unblocked"

    # Expire the bypass session (simulate time passing)
    db.cancel_session(bypass_session)

    # Instagram session should still be active
    active = db.get_active_sessions()
    assert len(active) == 1, "Instagram should still be active after bypass ends"
    assert active[0]['id'] == instagram_session, "Remaining active should be instagram"

    # Only instagram's domains should remain unblocked
    remaining_unblocked = db.get_all_domains_from_sessions()
    assert remaining_unblocked == ['instagram.com'], "Only instagram should remain unblocked"


def test_independent_with_wait_time(db):
    """Test that independent sessions with wait>0 become pending but don't queue"""
    # Create a pending session for all domains
    all_domains = ['youtube.com', 'reddit.com']
    session1 = db.create_session(
        profile='unblock',
        domains=all_domains,
        wait_minutes=5,
        duration_minutes=30
    )

    # First session should be pending
    pending = db.get_pending_sessions()
    assert len(pending) == 1, "First session should be pending"

    # Create an independent session with wait time (like quick with 0.5 min)
    # Even with same domains, it should be pending (not waiting)
    session2 = db.create_session(
        profile='quick',
        domains=all_domains,
        wait_minutes=1,
        duration_minutes=1,
        independent=True
    )

    # Both sessions should be pending (independent doesn't queue)
    pending = db.get_pending_sessions()
    waiting = db.get_waiting_sessions()

    assert len(pending) == 2, "Both sessions should be pending"
    assert len(waiting) == 0, "No sessions should be waiting"


def test_two_independent_sessions_same_domains(db):
    """Test that two independent sessions with same domains both run (no queueing)"""
    all_domains = ['youtube.com', 'reddit.com']

    # Create first independent session
    session1 = db.create_session(
        profile='bypass',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=5,
        independent=True
    )

    # Create second independent session with same domains
    session2 = db.create_session(
        profile='bypass',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=5,
        independent=True
    )

    # Both should be active (independent sessions don't queue against each other)
    active = db.get_active_sessions()
    waiting = db.get_waiting_sessions()

    assert len(active) == 2, "Both independent sessions should be active"
    assert len(waiting) == 0, "No sessions should be waiting"


def test_non_independent_wait_zero_still_would_cancel(db):
    """Test that non-independent sessions with wait=0 would still queue (cancellation is in CLI layer)

    Note: The actual cancellation logic is in alwaysblock.py, not db.py.
    This test verifies that non-independent sessions still queue at the DB level.
    The CLI decides whether to cancel based on the profile's independent flag.
    """
    all_domains = ['youtube.com', 'reddit.com']

    # Create first session (active)
    session1 = db.create_session(
        profile='unblock',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=30,
        independent=False
    )

    # Create second non-independent session with same domains
    # At DB level, it should queue (CLI would cancel the first one instead)
    session2 = db.create_session(
        profile='unblock',
        domains=all_domains,
        wait_minutes=0,
        duration_minutes=30,
        independent=False
    )

    # First should be active, second should be waiting (exact same domains)
    active = db.get_active_sessions()
    waiting = db.get_waiting_sessions()

    assert len(active) == 1, "First session should be active"
    assert len(waiting) == 1, "Second non-independent session should queue"
    assert waiting[0]['id'] == session2, "Session 2 should be waiting"
