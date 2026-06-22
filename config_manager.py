"""
Configuration manager for alwaysblock
Simplified from taviblock - keeps YAML format compatibility
"""
import logging
import yaml
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from threading import RLock

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages YAML configuration and domain blocking state"""
    
    def __init__(self, config_path: Path, db=None):
        self.config_path = config_path
        self._config_data: Dict = {}
        self._lock = RLock()
        self.db = db  # Database instance for session tracking
        
    def load(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                self._config_data = yaml.safe_load(f) or {}
            logger.info(f"Loaded configuration from {self.config_path}")
                
        except FileNotFoundError:
            logger.warning(f"Config file not found at {self.config_path}, using defaults")
            self._config_data = {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def get_all_configured_domains(self) -> List[str]:
        """Get all domains defined in configuration"""
        domains = []
        domain_config = self._config_data.get('domains', {})

        for name, config in domain_config.items():
            if isinstance(config, dict) and 'domains' in config:
                # Domain group
                domains.extend(config['domains'])
            else:
                # Individual domain
                domains.append(name)

        return list(set(domains))

    def get_excluded_domains(self) -> List[str]:
        """Get all globally excluded domains from configuration"""
        excluded = self._config_data.get('excluded_domains', [])
        if isinstance(excluded, list):
            return list(set(excluded))
        return []

    def get_backends(self) -> Dict[str, bool]:
        """Return which enforcement backends are enabled for this machine.

        Two independent backends can block, alone or together:
          - 'proxy':     the system-wide HTTP/HTTPS proxy (covers every app and
                         browser, including Safari and Chrome Incognito).
          - 'extension': the Chrome extension (covers Chrome tabs, including
                         tabs whose traffic a third-party proxy extension reroutes
                         away from the system proxy).

        This is intentionally a per-machine decision living in the user's local
        config.yaml, NOT a repo default. When the key is absent we fall back to
        proxy-only, which is the historical behavior, so existing installs are
        unaffected.
        """
        backends = self._config_data.get('backends', {})
        if not isinstance(backends, dict):
            backends = {}
        return {
            'proxy': bool(backends.get('proxy', True)),
            'extension': bool(backends.get('extension', False)),
        }

    def get_profiles_summary(self) -> Dict[str, Any]:
        """Compact, side-effect-free view of profiles for UI clients (the block
        page's profile picker). Returns {name: {wait, duration, cooldown}}.

        'wait' here is the profile's *base* wait in minutes; the real wait shown
        to the user is computed server-side by calculate_timing() at unblock time
        (it can add concurrent penalties and tag overrides). This is only enough
        for the picker to show a rough "~N min" next to each profile name.
        """
        summary = {}
        for name, profile in self.profiles.items():
            if not isinstance(profile, dict):
                profile = {}
            wait = profile.get('wait', 5)
            if isinstance(wait, dict):
                wait = wait.get('base', 5)
            summary[name] = {
                'wait': wait,
                'duration': profile.get('duration', 30),
                'cooldown': profile.get('cooldown', 0),
            }
        return summary
    
    def resolve_domains(self, targets: List[str]) -> tuple[List[str], List[str]]:
        """Resolve domain names/groups to actual domains

        Returns:
            (resolved_domains, invalid_targets) - lists of valid domains and invalid inputs
        """
        domains = []
        invalid = []
        domain_config = self._config_data.get('domains', {})

        for target in targets:
            target = target.strip()
            matched = False

            # Direct match
            if target in domain_config:
                config = domain_config[target]
                if isinstance(config, dict) and 'domains' in config:
                    # Domain group
                    domains.extend(config['domains'])
                else:
                    # Individual domain
                    domains.append(target)
                matched = True
                continue

            # Try with .com suffix
            if not target.endswith('.com') and (target + '.com') in domain_config:
                target_com = target + '.com'
                config = domain_config[target_com]
                if isinstance(config, dict) and 'domains' in config:
                    domains.extend(config['domains'])
                else:
                    domains.append(target_com)
                matched = True
                continue

            # Try other common TLDs
            common_tlds = ['.org', '.net', '.io', '.dev']
            for tld in common_tlds:
                if not any(target.endswith(t) for t in common_tlds + ['.com']) and (target + tld) in domain_config:
                    target_with_tld = target + tld
                    config = domain_config[target_with_tld]
                    if isinstance(config, dict) and 'domains' in config:
                        domains.extend(config['domains'])
                    else:
                        domains.append(target_with_tld)
                    matched = True
                    break

            if not matched:
                # Not found in config
                invalid.append(target)

        return (list(set(domains)), invalid)
    
    def resolve_host_to_target(self, host: str) -> Optional[str]:
        """Map a concrete browser host to the config target that unblocks it.

        The Chrome extension only knows the host the user navigated to (which may
        be a subdomain like 'old.reddit.com' or a group member like 'x.com').
        unblock() expects a config key — a domain name or a group name — so we
        translate here, picking the most specific (longest) matching member and
        returning its group name when it belongs to a group.

        Returns None if the host isn't covered by any configured domain.
        """
        host = host.split(':')[0].strip().lower()
        if host.startswith('www.'):
            host = host[4:]

        domain_config = self._config_data.get('domains', {})
        best_target = None
        best_len = -1

        for name, config in domain_config.items():
            if isinstance(config, dict) and 'domains' in config:
                members = [(m, name) for m in config['domains']]  # member -> group name
            else:
                members = [(name, name)]
            for member, target in members:
                member_l = str(member).lower()
                if host == member_l or host.endswith('.' + member_l):
                    if len(member_l) > best_len:
                        best_len = len(member_l)
                        best_target = target

        return best_target

    def is_domain_blocked(self, domain: str) -> bool:
        """Check if a domain is currently blocked based on configuration and active sessions"""
        if not self.db:
            return False  # Allow by default if no DB
            
        # Remove port if present
        domain = domain.split(':')[0]
        
        # Get all configured domains
        configured_domains = set(self.get_all_configured_domains())
        
        # Check if domain is in configuration
        domain_in_config = False
        
        # Check exact match
        if domain in configured_domains:
            domain_in_config = True
        else:
            # Check parent domains (e.g., mail.google.com -> google.com)
            parts = domain.split('.')
            for i in range(len(parts) - 1):
                parent = '.'.join(parts[i:])
                if parent in configured_domains:
                    domain_in_config = True
                    break
        
        # If not in config, don't block it
        if not domain_in_config:
            return False
            
        # Domain is in config - now check if it's in active unblock sessions
        active_domains = set(self.db.get_all_domains_from_sessions())
        
        # Check exact match in active sessions
        if domain in active_domains:
            return False
            
        # Check parent domains in active sessions
        parts = domain.split('.')
        for i in range(len(parts) - 1):
            parent = '.'.join(parts[i:])
            if parent in active_domains:
                return False
                
        # Domain is configured but not in active sessions - block it
        return True
    
    def calculate_timing(self, profile_name: str, targets: List[str]) -> Dict[str, Any]:
        """Calculate wait and duration for a profile with targets"""
        profile = self.profiles.get(profile_name, {})

        # Get all tags from targets
        all_tags = set()
        domain_config = self._config_data.get('domains', {})
        for target in targets:
            if target in domain_config:
                config = domain_config[target]
                if isinstance(config, dict) and 'tags' in config:
                    all_tags.update(config['tags'])

        # Calculate base wait time
        wait = 5  # Default
        explanation_parts = []

        if isinstance(profile.get('wait'), (int, float)):
            wait = profile['wait']
            explanation_parts.append(f"base {wait} min")
        elif isinstance(profile.get('wait'), dict):
            wait_config = profile['wait']
            base = wait_config.get('base', 5)
            explanation_parts.append(f"base {base} min")

            # Add concurrent penalty if DB available
            concurrent_penalty = 0
            if self.db and 'concurrent_penalty' in wait_config:
                concurrent_count = self.db.count_concurrent_pending(profile_name)
                concurrent_penalty = wait_config['concurrent_penalty'] * concurrent_count
                if concurrent_penalty > 0:
                    explanation_parts.append(f"+{concurrent_penalty} min ({concurrent_count} pending × {wait_config['concurrent_penalty']} min penalty)")

            wait = base + concurrent_penalty

        # Check for tag-based overrides
        has_override = False
        if 'tag_rules' in profile:
            for rule in profile['tag_rules']:
                if 'tags' in rule:
                    # Check if any of the rule's tags are in our tags
                    if any(tag in all_tags for tag in rule['tags']):
                        if 'wait_override' in rule:
                            wait = rule['wait_override']
                            matching_tags = [tag for tag in rule['tags'] if tag in all_tags]
                            explanation_parts = [f"{wait} min (override for tags: {', '.join(matching_tags)})"]
                            has_override = True
                            break

        duration = profile.get('duration', 30)
        cooldown = profile.get('cooldown', 0)

        explanation = " ".join(explanation_parts) if explanation_parts else f"{wait} min"

        return {
            'wait': wait,
            'duration': duration,
            'cooldown': cooldown,
            'explanation': explanation,
            'has_override': has_override
        }
    
    @property
    def profiles(self) -> Dict[str, Any]:
        """Get profiles from config"""
        return self._config_data.get('profiles', {})
    
    def get_profile_names(self) -> List[str]:
        """Get all available profile names"""
        return list(self.profiles.keys())
    
    def is_valid_profile(self, profile_name: str) -> bool:
        """Check if a profile exists"""
        return profile_name in self.profiles
    
    def get_default_profile(self) -> Optional[str]:
        """Get the default profile name if specified"""
        return self._config_data.get('default_profile', 'unblock')

    def get_profile_target_type(self, profile_name: str) -> Optional[str]:
        """Get target_type for a profile: 'all', 'single', or None (legacy behavior)"""
        profile = self.profiles.get(profile_name, {})
        return profile.get('target_type')

    def is_profile_independent(self, profile_name: str) -> bool:
        """Check if profile runs independently (doesn't conflict with other sessions)

        Default: True if target_type is 'all', False otherwise.
        Can be explicitly overridden with 'independent: true/false' in config.
        """
        profile = self.profiles.get(profile_name, {})
        # Explicit setting takes precedence
        if 'independent' in profile:
            return profile['independent']
        # Default: 'all' profiles are independent
        return profile.get('target_type') == 'all'