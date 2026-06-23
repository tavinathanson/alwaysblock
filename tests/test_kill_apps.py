#!/usr/bin/env python3
"""Tests for the opt-in app-watchdog config (kill_apps)."""

import tempfile
from pathlib import Path

import yaml
import pytest

from config_manager import ConfigManager


def _cm(config: dict) -> ConfigManager:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(config, f)
    f.close()
    cm = ConfigManager(str(Path(f.name)))
    cm.load()
    return cm


BASE_DOMAINS = {
    'domains': {
        'slack': {'domains': ['slack.com', 'slack-edge.com', 'api.slack.com']},
        'reddit.com': {},
    }
}


def test_off_by_default():
    """No kill_apps block → nothing is ever watched."""
    assert _cm(BASE_DOMAINS).get_kill_apps() == []


def test_group_resolves_to_member_domains():
    cm = _cm({**BASE_DOMAINS, 'kill_apps': [{'app': 'Slack', 'when_blocked': ['slack']}]})
    apps = cm.get_kill_apps()
    assert len(apps) == 1
    assert apps[0]['app'] == 'Slack'
    assert set(apps[0]['domains']) == {'slack.com', 'slack-edge.com', 'api.slack.com'}


def test_when_blocked_accepts_a_bare_string():
    cm = _cm({**BASE_DOMAINS, 'kill_apps': [{'app': 'Reddit', 'when_blocked': 'reddit.com'}]})
    assert cm.get_kill_apps() == [{'app': 'Reddit', 'domains': ['reddit.com']}]


def test_invalid_and_empty_entries_are_skipped():
    cm = _cm({**BASE_DOMAINS, 'kill_apps': [
        {'app': 'Ghost', 'when_blocked': ['does-not-exist']},  # unresolvable target
        {'app': '', 'when_blocked': ['slack']},                # no app name
        {'when_blocked': ['slack']},                           # missing app key
        'not-a-dict',                                          # wrong shape
        {'app': 'Slack', 'when_blocked': ['slack']},           # the one valid entry
    ]})
    apps = cm.get_kill_apps()
    assert [a['app'] for a in apps] == ['Slack']


def test_malformed_kill_apps_block_is_ignored():
    cm = _cm({**BASE_DOMAINS, 'kill_apps': 'nonsense'})
    assert cm.get_kill_apps() == []


# --- watchdog decision logic --------------------------------------------------

import watchdog


class _FakeBrain:
    """Minimal stand-in for the brain the watchdog reads."""
    def __init__(self, blocked, pause_until=0.0):
        self._blocked = set(blocked)
        self._pause_until = pause_until

    def _get_pause_until(self):
        return self._pause_until

    class _CM:
        pass


def _brain(blocked, pause_until=0.0):
    b = _FakeBrain(blocked, pause_until)
    b.config_manager = _FakeBrain._CM()
    b.config_manager.is_domain_blocked = lambda d: d in b._blocked
    return b


def test_should_be_blocked_when_any_domain_blocked():
    b = _brain({'slack.com'})
    assert watchdog._should_be_blocked(b, ['slack.com', 'api.slack.com']) is True


def test_not_blocked_when_no_domain_blocked():
    b = _brain(set())
    assert watchdog._should_be_blocked(b, ['slack.com']) is False


def test_pause_disables_killing(monkeypatch):
    """During an active pause/disable, nothing should be quit even if blocked."""
    monkeypatch.setattr(watchdog.time, 'time', lambda: 1000.0)
    b = _brain({'slack.com'}, pause_until=2000.0)  # paused until later
    assert watchdog._should_be_blocked(b, ['slack.com']) is False


def test_quit_app_uses_exact_match_pkill(monkeypatch):
    calls = []
    monkeypatch.setattr(watchdog.subprocess, 'run', lambda *a, **k: calls.append(a[0]) or None)
    watchdog._quit_app('Slack')
    assert calls == [['pkill', '-x', 'Slack']]


def test_app_is_running_reads_pgrep_exit_code(monkeypatch):
    class _R:
        def __init__(self, rc): self.returncode = rc
    monkeypatch.setattr(watchdog.subprocess, 'run', lambda *a, **k: _R(0))
    assert watchdog._app_is_running('Slack') is True
    monkeypatch.setattr(watchdog.subprocess, 'run', lambda *a, **k: _R(1))
    assert watchdog._app_is_running('Slack') is False
