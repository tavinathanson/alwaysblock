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


# --- host -> target resolution (used by the bridge /unblock) --------------
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


# --- profile summary (block-page picker) ----------------------------------
def test_profiles_summary_shapes_base_wait():
    cm = make_cm({"profiles": {
        "unblock": {"wait": {"base": 5, "concurrent_penalty": 5}, "duration": 30},
        "quick": {"wait": 0.5, "duration": 1, "cooldown": 2},
    }})
    summary = cm.get_profiles_summary()
    assert summary["unblock"] == {"wait": 5, "duration": 30, "cooldown": 0}
    assert summary["quick"] == {"wait": 0.5, "duration": 1, "cooldown": 2}


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
    assert blob["default_profile"] == "unblock"
    assert "unblock" in blob["profiles"]
    assert blob["unblocked"] == {}
    assert blob["active_sessions"] == []
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
