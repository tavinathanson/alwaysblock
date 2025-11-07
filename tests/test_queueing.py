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


def test_serial_unblock_multiple_targets(db):
    """Test that unblocking multiple different domains with queue_after creates serial sessions

    This simulates: alwaysblock unblock gmail slack facebook
    Each should create a separate session that queues after the previous one,
    even though they have different domains (using the queue_after parameter).
    """
    # Create sessions for different domains serially (as if user ran: unblock gmail slack facebook)
    targets = [
        ['gmail.com'],
        ['slack.com'],
        ['facebook.com']
    ]

    session_ids = []
    last_end_time = None

    for domains in targets:
        session_id = db.create_session(
            profile='test',
            domains=domains,
            wait_minutes=1,
            duration_minutes=5,
            queue_after=last_end_time  # Force serial queueing
        )
        session_ids.append(session_id)

        # Get the session we just created to track its end time
        sessions = db.get_pending_sessions() + db.get_active_sessions()
        session = next(s for s in sessions if s['id'] == session_id)
        last_end_time = session['end_at']

    # Get all sessions
    sessions = db.get_pending_sessions()
    assert len(sessions) == 3, "Should have 3 pending sessions"

    # Sort by start time
    sessions.sort(key=lambda s: s['start_at'])

    # Verify they queue sequentially (each starts after previous ends + wait time)
    for i in range(len(sessions) - 1):
        current = sessions[i]
        next_session = sessions[i + 1]

        assert next_session['start_at'] > current['end_at'], \
            f"Session {i+1} should start after session {i} ends"

        gap_minutes = (next_session['start_at'] - current['end_at']).total_seconds() / 60
        assert abs(gap_minutes - 1.0) < 0.01, \
            f"Gap between session {i} and {i+1} should be 1 minute, got {gap_minutes}"
