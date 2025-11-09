"""
Tests for tag override sessions not counting toward concurrent penalty
"""
import pytest
from pathlib import Path
from db import Database
from config_manager import ConfigManager


@pytest.fixture
def db(tmp_path):
    """Create a temporary database"""
    db_path = tmp_path / "test.db"
    return Database(db_path)


@pytest.fixture
def config_manager(tmp_path):
    """Create config manager with test configuration"""
    config_path = tmp_path / "config.yaml"

    # Create a test config with override tags
    config_content = """
default_profile: unblock

domains:
  gmail:
    domains:
      - gmail.com
      - mail.google.com
    tags: [communication, work]

  slack:
    domains:
      - slack.com
    tags: [communication, work]

  facebook:
    domains:
      - facebook.com
    tags: [social, distracting]

  instagram:
    domains:
      - instagram.com
    tags: [social, distracting]

profiles:
  unblock:
    description: "Standard unblock with wait time"
    wait:
      base: 5
      concurrent_penalty: 5
    duration: 30

    tag_rules:
      - tags: [work, communication]
        wait_override: 1
"""

    with open(config_path, 'w') as f:
        f.write(config_content)

    cm = ConfigManager(config_path, db=None)
    cm.load()
    return cm


def test_override_sessions_dont_count_in_penalty(db, config_manager):
    """Test that sessions with tag overrides don't contribute to concurrent penalty"""
    config_manager.db = db

    # Create gmail session (should have override)
    gmail_timing = config_manager.calculate_timing('unblock', ['gmail'])
    assert gmail_timing['wait'] == 1
    assert gmail_timing['has_override'] == True

    gmail_session_id = db.create_session(
        profile='unblock',
        domains=['gmail.com', 'mail.google.com'],
        wait_minutes=gmail_timing['wait'],
        duration_minutes=gmail_timing['duration'],
        has_override=gmail_timing['has_override']
    )

    # Create slack session (should have override)
    slack_timing = config_manager.calculate_timing('unblock', ['slack'])
    assert slack_timing['wait'] == 1
    assert slack_timing['has_override'] == True

    slack_session_id = db.create_session(
        profile='unblock',
        domains=['slack.com'],
        wait_minutes=slack_timing['wait'],
        duration_minutes=slack_timing['duration'],
        has_override=slack_timing['has_override']
    )

    # Now check concurrent count - should be 0 because override sessions don't count
    concurrent_count = db.count_concurrent_pending('unblock')
    assert concurrent_count == 0, "Override sessions should not count toward concurrent penalty"

    # Create facebook session (no override)
    facebook_timing = config_manager.calculate_timing('unblock', ['facebook'])
    assert facebook_timing['has_override'] == False

    # Should get base wait (5) + 0 penalty (no non-override sessions pending)
    expected_wait = 5 + (concurrent_count * 5)
    assert facebook_timing['wait'] == expected_wait

    facebook_session_id = db.create_session(
        profile='unblock',
        domains=['facebook.com'],
        wait_minutes=facebook_timing['wait'],
        duration_minutes=facebook_timing['duration'],
        has_override=facebook_timing['has_override']
    )

    # Now concurrent count should be 1 (just facebook)
    concurrent_count = db.count_concurrent_pending('unblock')
    assert concurrent_count == 1

    # Create instagram session (no override)
    instagram_timing = config_manager.calculate_timing('unblock', ['instagram'])
    assert instagram_timing['has_override'] == False

    # Should get base wait (5) + 5 penalty (1 non-override session pending: facebook)
    expected_wait = 5 + (concurrent_count * 5)
    assert instagram_timing['wait'] == expected_wait == 10


def test_order_independence_with_overrides(db, config_manager):
    """Test that order doesn't matter when mixing override and non-override sessions"""
    config_manager.db = db

    # Scenario 1: gmail, slack, facebook, instagram
    # Reset db
    db_path = db.db_path
    db = Database(db_path)
    config_manager.db = db

    timings_1 = []
    for target in ['gmail', 'slack', 'facebook', 'instagram']:
        timing = config_manager.calculate_timing('unblock', [target])
        timings_1.append((target, timing['wait'], timing['has_override']))

    # Scenario 2: facebook, instagram, gmail, slack
    db_path_2 = db_path.parent / "test2.db"
    db2 = Database(db_path_2)
    config_manager.db = db2

    timings_2 = []
    for target in ['facebook', 'instagram', 'gmail', 'slack']:
        timing = config_manager.calculate_timing('unblock', [target])
        timings_2.append((target, timing['wait'], timing['has_override']))

    # Extract just the timings for comparison
    gmail_wait_1 = next(t[1] for t in timings_1 if t[0] == 'gmail')
    slack_wait_1 = next(t[1] for t in timings_1 if t[0] == 'slack')
    facebook_wait_1 = next(t[1] for t in timings_1 if t[0] == 'facebook')
    instagram_wait_1 = next(t[1] for t in timings_1 if t[0] == 'instagram')

    gmail_wait_2 = next(t[1] for t in timings_2 if t[0] == 'gmail')
    slack_wait_2 = next(t[1] for t in timings_2 if t[0] == 'slack')
    facebook_wait_2 = next(t[1] for t in timings_2 if t[0] == 'facebook')
    instagram_wait_2 = next(t[1] for t in timings_2 if t[0] == 'instagram')

    # gmail and slack should always get 1 min (override)
    assert gmail_wait_1 == gmail_wait_2 == 1
    assert slack_wait_1 == slack_wait_2 == 1

    # facebook and instagram should get same wait times regardless of order
    # (because gmail/slack don't count in penalty)
    assert facebook_wait_1 == facebook_wait_2
    assert instagram_wait_1 == instagram_wait_2
