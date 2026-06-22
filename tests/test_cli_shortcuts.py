#!/usr/bin/env python3
"""Guard the profile-name shortcut (e.g. `alwaysblock bypass reddit`).

This rewrite is what lets a profile name be used as a top-level command. It is
easy to break when editing main(), so it lives in a pure function and is pinned
here.
"""
from alwaysblock import rewrite_profile_shortcut

PROFILES = ["unblock", "quick", "bypass"]


def test_bypass_with_target():
    assert rewrite_profile_shortcut(["ab", "bypass", "reddit"], PROFILES) == \
        ["ab", "unblock", "-p", "bypass", "reddit"]


def test_bypass_bare():
    assert rewrite_profile_shortcut(["ab", "bypass"], PROFILES) == \
        ["ab", "unblock", "-p", "bypass"]


def test_bypass_multiple_targets():
    assert rewrite_profile_shortcut(["ab", "quick", "reddit", "twitter"], PROFILES) == \
        ["ab", "unblock", "-p", "quick", "reddit", "twitter"]


def test_real_command_unchanged():
    # Commands that are NOT profile names must pass through untouched. (Note
    # 'unblock' IS a profile name in the default config, so it is intentionally
    # excluded here — `alwaysblock unblock` rewriting to `unblock -p unblock` is
    # existing, harmless behavior.)
    for cmd in ("status", "start", "stop", "bridge", "block-all", "cancel"):
        assert rewrite_profile_shortcut(["ab", cmd], PROFILES) == ["ab", cmd]


def test_bridge_is_not_a_profile():
    # Regression: the new 'bridge' subcommand must not be swallowed by the
    # shortcut even if someone names a profile 'bridge'.
    assert rewrite_profile_shortcut(["ab", "bridge", "status"], PROFILES) == \
        ["ab", "bridge", "status"]


def test_no_args_unchanged():
    assert rewrite_profile_shortcut(["ab"], PROFILES) == ["ab"]
