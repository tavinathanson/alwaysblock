#!/usr/bin/env python3
"""Tests for the backend-agnostic state blob and the brain helpers the Chrome
backend depends on (backend toggle, host->target resolution, profile summary,
and the enriched _write_state output)."""
import tempfile
from pathlib import Path

import pytest
import yaml

from config_manager import ConfigManager


def make_cm(config: dict) -> ConfigManager:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(config, f)
    f.close()
    cm = ConfigManager(str(Path(f.name)))
    cm.load()
    return cm


# --- backend toggle -------------------------------------------------------
def test_backends_default_is_proxy_only():
    cm = make_cm({"domains": {"reddit.com": {}}})
    assert cm.get_backends() == {"proxy": True, "extension": False}


def test_backends_explicit_both():
    cm = make_cm({"backends": {"proxy": True, "extension": True}})
    assert cm.get_backends() == {"proxy": True, "extension": True}


def test_backends_extension_only():
    cm = make_cm({"backends": {"proxy": False, "extension": True}})
    assert cm.get_backends() == {"proxy": False, "extension": True}


# --- host -> target resolution (used by the bridge /resolve) --------------
@pytest.fixture
def grouped_cm():
    return make_cm({
        "domains": {
            "reddit.com": {},
            "twitter": {"domains": ["twitter.com", "x.com", "t.co"]},
        },
        "excluded_domains": ["accounts.google.com"],
        "profiles": {"unblock": {"wait": 5, "duration": 30}},
    })


def test_resolve_plain_subdomain(grouped_cm):
    assert grouped_cm.resolve_host_to_target("old.reddit.com") == "reddit.com"


def test_resolve_www_stripped(grouped_cm):
    assert grouped_cm.resolve_host_to_target("www.reddit.com") == "reddit.com"


def test_resolve_group_member_returns_group_name(grouped_cm):
    # A group member host should resolve to the GROUP name unblock() understands.
    assert grouped_cm.resolve_host_to_target("x.com") == "twitter"
    assert grouped_cm.resolve_host_to_target("mobile.twitter.com") == "twitter"


def test_resolve_unconfigured_host_is_none(grouped_cm):
    assert grouped_cm.resolve_host_to_target("example.com") is None


# --- the enriched state blob (_write_state) -------------------------------
@pytest.fixture
def brain(tmp_path, monkeypatch):
    """An AlwaysBlock wired to a temp HOME so it never touches the real install,
    with its state file redirected away from /tmp."""
    home = tmp_path
    (home / ".config" / "alwaysblock").mkdir(parents=True)
    (home / ".local" / "share" / "alwaysblock").mkdir(parents=True)
    config = {
        "default_profile": "unblock",
        "excluded_domains": ["accounts.google.com"],
        "domains": {
            "reddit.com": {},
            "twitter": {"domains": ["twitter.com", "x.com"]},
        },
        "profiles": {"unblock": {"wait": 5, "duration": 30}},
    }
    with open(home / ".config" / "alwaysblock" / "config.yaml", "w") as f:
        yaml.dump(config, f)

    monkeypatch.setenv("HOME", str(home))
    from alwaysblock import AlwaysBlock
    ab = AlwaysBlock()
    # Redirect the shared state file so the test can't clobber a running install.
    ab.json_path = home / "state.json"
    return ab


def test_state_blob_basic_shape(brain):
    blob = brain._write_state()
    assert blob["schema_version"] == 2
    assert blob["unblocked"] == {}
    assert blob["active_sessions"] == []
    assert blob["pending_sessions"] == []
    assert blob["waiting_sessions"] == []
    # group expands to members; excluded present
    assert "reddit.com" in blob["domains"]
    assert "twitter.com" in blob["domains"] and "x.com" in blob["domains"]
    assert "accounts.google.com" in blob["excluded"]
    # nothing unblocked yet => no pause
    assert "pause_until" not in blob


def test_state_blob_reflects_disable(brain):
    brain.disable()  # disable until midnight -> sets pause_until
    blob = brain._write_state()
    assert blob.get("pause_until", 0) > 0


# --- travel mode ----------------------------------------------------------
class StubSystemProxy:
    """Stands in for SystemProxy so tests never touch networksetup."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = []

    def get_status(self):
        return {"enabled": self.enabled, "services_count": 1, "enabled_count": int(self.enabled)}

    def enable_proxy(self):
        self.calls.append("enable")
        self.enabled = True

    def disable_proxy(self):
        self.calls.append("disable")
        self.enabled = False


@pytest.fixture
def travel_brain(brain, monkeypatch):
    brain.system_proxy = StubSystemProxy(enabled=True)
    monkeypatch.setattr(brain, "is_proxy_running", lambda: True)
    monkeypatch.setattr(brain, "is_bridge_running", lambda: True)
    return brain


def test_travel_pauses_for_an_hour_and_disables_system_proxy(travel_brain):
    import time
    travel_brain.travel()
    pause_until = travel_brain._get_pause_until()
    assert 3590 < pause_until - time.time() <= 3600
    assert travel_brain.system_proxy.calls == ["disable"]
    # The pause is in the state blob, so the extension (via the bridge) sees it.
    assert travel_brain._write_state().get("pause_until") == pause_until


def test_travel_repeats_add_an_hour_each(travel_brain):
    import time
    travel_brain.travel()
    travel_brain.travel()
    assert 7190 < travel_brain._get_pause_until() - time.time() <= 7200
    # System proxy already off on the second run -> only one disable call.
    assert travel_brain.system_proxy.calls == ["disable"]


def test_resume_after_travel_restores_system_proxy(travel_brain):
    travel_brain.travel()
    travel_brain.resume()
    assert travel_brain._get_pause_until() == 0.0
    assert travel_brain.system_proxy.calls == ["disable", "enable"]


def test_resume_after_travel_without_proxy_daemon_does_not_enable(travel_brain, monkeypatch):
    # Pointing the system proxy at a dead daemon would black-hole traffic.
    monkeypatch.setattr(travel_brain, "is_proxy_running", lambda: False)
    travel_brain.travel()
    travel_brain.resume()
    assert travel_brain.system_proxy.calls == ["disable"]


def test_paused_exit_codes(travel_brain):
    with pytest.raises(SystemExit) as e:
        travel_brain.paused()
    assert e.value.code == 1
    travel_brain.travel()
    with pytest.raises(SystemExit) as e:
        travel_brain.paused()
    assert e.value.code == 0
