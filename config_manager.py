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
    
    def resolve_domains(self, targets: List[str]) -> List[str]:
        """Resolve domain names/groups to actual domains"""
        domains = []
        domain_config = self._config_data.get('domains', {})
        
        for target in targets:
            target = target.strip()
            
            # Direct match
            if target in domain_config:
                config = domain_config[target]
                if isinstance(config, dict) and 'domains' in config:
                    # Domain group
                    domains.extend(config['domains'])
                else:
                    # Individual domain
                    domains.append(target)
                continue
                
            # Try with .com suffix
            if not target.endswith('.com') and (target + '.com') in domain_config:
                target_com = target + '.com'
                config = domain_config[target_com]
                if isinstance(config, dict) and 'domains' in config:
                    domains.extend(config['domains'])
                else:
                    domains.append(target_com)
                continue
                
            # Not in config - treat as raw domain
            domains.append(target)
            
        return list(set(domains))
    
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
        if isinstance(profile.get('wait'), (int, float)):
            wait = profile['wait']
        elif isinstance(profile.get('wait'), dict):
            wait_config = profile['wait']
            base = wait_config.get('base', 5)
            
            # Add concurrent penalty if DB available
            concurrent_penalty = 0
            if self.db and 'concurrent_penalty' in wait_config:
                concurrent_count = self.db.count_concurrent_pending(profile_name)
                concurrent_penalty = wait_config['concurrent_penalty'] * concurrent_count
            
            wait = base + concurrent_penalty
        
        # Check for tag-based overrides
        if 'tag_rules' in profile:
            for rule in profile['tag_rules']:
                if 'tags' in rule:
                    # Check if any of the rule's tags are in our tags
                    if any(tag in all_tags for tag in rule['tags']):
                        if 'wait_override' in rule:
                            wait = rule['wait_override']
                            break
        
        duration = profile.get('duration', 30)
        cooldown = profile.get('cooldown', 0)
        
        return {
            'wait': wait,
            'duration': duration,
            'cooldown': cooldown
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