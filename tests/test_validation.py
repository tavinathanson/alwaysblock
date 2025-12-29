#!/usr/bin/env python3
"""Test domain validation"""

import pytest
from config_manager import ConfigManager
from pathlib import Path
import tempfile
import yaml


@pytest.fixture
def config_manager():
    """Create a config manager with test configuration"""
    test_config = {
        'domains': {
            'youtube.com': {
                'domains': ['youtube.com', 'googlevideo.com', 'ytimg.com']
            },
            'reddit.com': {},
            'twitter.com': {},
            'github.io': {},
        },
        'profiles': {
            'unblock': {
                'wait': 1,
                'duration': 5,
                'cooldown': 0
            }
        }
    }

    # Write to temp file
    temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(test_config, temp_config)
    temp_config.close()
    config_path = Path(temp_config.name)

    # Create config manager
    cm = ConfigManager(str(config_path))
    cm.load()

    yield cm

    # Cleanup
    config_path.unlink(missing_ok=True)


def test_valid_domain_name(config_manager):
    """Test that a valid domain name resolves to all group domains"""
    resolved, invalid = config_manager.resolve_domains(['youtube.com'])

    assert len(resolved) == 3, "Should resolve youtube.com to 3 domains"
    assert 'youtube.com' in resolved
    assert 'googlevideo.com' in resolved
    assert 'ytimg.com' in resolved
    assert len(invalid) == 0, "Should have no invalid domains"


def test_domain_without_tld(config_manager):
    """Test that domain without .com auto-adds it and resolves"""
    resolved, invalid = config_manager.resolve_domains(['youtube'])

    assert len(resolved) == 3, "Should auto-add .com and resolve to 3 domains"
    assert 'youtube.com' in resolved
    assert len(invalid) == 0, "Should have no invalid domains"


def test_invalid_nonsense(config_manager):
    """Test that nonsense input is marked as invalid"""
    resolved, invalid = config_manager.resolve_domains(['asdfasdfasdf'])

    assert len(resolved) == 0, "Should not resolve nonsense"
    assert 'asdfasdfasdf' in invalid, "Should mark nonsense as invalid"


def test_mix_valid_and_invalid(config_manager):
    """Test that valid domains resolve and invalid ones are marked"""
    resolved, invalid = config_manager.resolve_domains(['youtube', 'nonsense', 'reddit'])

    assert len(resolved) > 0, "Should resolve valid domains"
    assert 'youtube.com' in resolved or 'reddit.com' in resolved
    assert 'nonsense' in invalid, "Should mark nonsense as invalid"
    assert len(invalid) == 1, "Should have exactly one invalid domain"


def test_individual_domain(config_manager):
    """Test that individual domains (not groups) resolve correctly"""
    resolved, invalid = config_manager.resolve_domains(['twitter.com'])

    assert 'twitter.com' in resolved, "Should resolve individual domain"
    assert len(invalid) == 0, "Should have no invalid domains"


def test_different_tld(config_manager):
    """Test that domains with different TLDs (.io, .org, etc) are detected"""
    resolved, invalid = config_manager.resolve_domains(['github'])

    assert 'github.io' in resolved, "Should try .io and find it"
    assert len(invalid) == 0, "Should have no invalid domains"


def test_multiple_valid_domains(config_manager):
    """Test resolving multiple valid domains at once"""
    resolved, invalid = config_manager.resolve_domains(['youtube', 'reddit', 'twitter'])

    assert len(resolved) >= 5, "Should resolve all domains (3 from youtube group + reddit + twitter)"
    assert 'youtube.com' in resolved
    assert 'reddit.com' in resolved
    assert 'twitter.com' in resolved
    assert len(invalid) == 0, "Should have no invalid domains"


def test_empty_input(config_manager):
    """Test that empty input returns empty results"""
    resolved, invalid = config_manager.resolve_domains([])

    assert len(resolved) == 0, "Should return no resolved domains"
    assert len(invalid) == 0, "Should return no invalid domains"


@pytest.fixture
def config_with_target_types():
    """Create a config manager with profiles that have target_type and independent settings"""
    test_config = {
        'domains': {
            'youtube.com': {},
            'reddit.com': {},
            'instagram.com': {},
        },
        'profiles': {
            'unblock': {
                'wait': 1,
                'duration': 30,
            },
            'bypass': {
                'wait': 0,
                'duration': 5,
                'target_type': 'all',
                # independent defaults to True for target_type: all
            },
            'quick': {
                'wait': 0.5,
                'duration': 1,
                'target_type': 'all',
                # independent defaults to True for target_type: all
            },
            'peek': {
                'wait': 0,
                'duration': 1,
                'target_type': 'single',
            },
            'legacy': {
                'wait': 1,
                'duration': 10,
                # No target_type - legacy behavior
            },
            'all_but_not_independent': {
                'wait': 0,
                'duration': 5,
                'target_type': 'all',
                'independent': False,  # Explicitly override the default
            }
        }
    }

    temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    yaml.dump(test_config, temp_config)
    temp_config.close()
    config_path = Path(temp_config.name)

    cm = ConfigManager(str(config_path))
    cm.load()

    yield cm

    config_path.unlink(missing_ok=True)


def test_target_type_all(config_with_target_types):
    """Test that profile with target_type 'all' returns correct value"""
    cm = config_with_target_types

    assert cm.get_profile_target_type('bypass') == 'all'
    assert cm.get_profile_target_type('quick') == 'all'


def test_target_type_single(config_with_target_types):
    """Test that profile with target_type 'single' returns correct value"""
    cm = config_with_target_types

    assert cm.get_profile_target_type('peek') == 'single'


def test_target_type_legacy(config_with_target_types):
    """Test that profile without target_type returns None (legacy behavior)"""
    cm = config_with_target_types

    assert cm.get_profile_target_type('legacy') is None
    assert cm.get_profile_target_type('unblock') is None


def test_independent_defaults_true_for_target_type_all(config_with_target_types):
    """Test that profiles with target_type='all' default to independent=True"""
    cm = config_with_target_types

    assert cm.is_profile_independent('bypass') is True
    assert cm.is_profile_independent('quick') is True


def test_independent_false_by_default_for_others(config_with_target_types):
    """Test that profiles without target_type='all' default to independent=False"""
    cm = config_with_target_types

    assert cm.is_profile_independent('unblock') is False
    assert cm.is_profile_independent('peek') is False
    assert cm.is_profile_independent('legacy') is False


def test_independent_explicit_override(config_with_target_types):
    """Test that explicit independent=False overrides the target_type='all' default"""
    cm = config_with_target_types

    # This profile has target_type='all' but explicitly sets independent=False
    assert cm.is_profile_independent('all_but_not_independent') is False
