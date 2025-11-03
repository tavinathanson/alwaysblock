#!/usr/bin/env python3
"""
alwaysblock CLI - Direct version (no daemon)
Works directly with SQLite DB and writes JSON for Network Extension
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
import os

# Import the existing modules we'll reuse
from config_manager import ConfigManager
from db import Database


class AlwaysBlockDirect:
    """Direct CLI implementation without daemon"""
    
    def __init__(self):
        # Use same paths as original
        self.config_path = Path.home() / '.config' / 'alwaysblock' / 'config.yaml'
        self.db_path = Path.home() / '.local' / 'share' / 'alwaysblock' / 'alwaysblock.db'
        
        # JSON file for Network Extension (using /tmp for local signing without App Groups)
        # Both CLI and system extension can access /tmp
        self.json_path = Path('/tmp/alwaysblock_domains.json')
        
        # Initialize components
        self.config_manager = ConfigManager(str(self.config_path))
        self.config_manager.load()  # Load the config
        self.db = Database(self.db_path)
        
    def _write_domains_for_extension(self):
        """Write current blocked domains to JSON file for Network Extension"""
        # Get all configured domains
        all_domains = self.config_manager.get_all_configured_domains()
        
        # Get active unblock sessions
        active_sessions = self.db.get_active_sessions()
        unblocked_domains = set()
        expirations = {}
        
        for session in active_sessions:
            for domain in session['domains']:
                unblocked_domains.add(domain)
                # Store earliest expiration if domain appears in multiple sessions
                end_time = session['end_at']
                if domain not in expirations or end_time < expirations[domain]:
                    expirations[domain] = end_time
        
        # Calculate what should be blocked (configured minus unblocked)
        blocked_domains = set(all_domains) - unblocked_domains
        
        # Expand domain groups to include CDNs
        expanded_blocked = set()
        for domain in blocked_domains:
            expanded_blocked.add(domain)
            # Check if domain is a group name
            for group_name, group_data in self.config_manager._config_data.get('domains', {}).items():
                if isinstance(group_data, dict) and 'domains' in group_data:
                    if group_name == domain or domain in group_data['domains']:
                        # Add all domains in the group
                        expanded_blocked.update(group_data['domains'])
        
        # Convert to format expected by Network Extension
        domains_data = {
            'domains': sorted(list(expanded_blocked)),
            'expirations': {}  # Network Extension doesn't use temporary blocks
        }
        
        # Write to JSON file
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_path, 'w') as f:
            json.dump(domains_data, f, indent=2)
            
    def status(self):
        """Show current status"""
        # Process any expired sessions first
        self._process_expired_sessions()
        
        # Update JSON for Network Extension
        self._write_domains_for_extension()
        
        active_sessions = self.db.get_active_sessions()
        pending_sessions = self.db.get_pending_sessions()
        all_configured = self.config_manager.get_all_configured_domains()
        
        # Collect unblocked domains
        unblocked_domains = set()
        for session in active_sessions:
            unblocked_domains.update(session['domains'])
        
        blocked_count = len(all_configured) - len(unblocked_domains)
        
        print(f"AlwaysBlock Status")
        print(f"==================")
        print(f"Configured domains: {len(all_configured)}")
        print(f"Currently blocked: {blocked_count}")
        print(f"Active unblock sessions: {len(active_sessions)}")
        print(f"Pending sessions: {len(pending_sessions)}")
        
        if active_sessions or pending_sessions:
            print("\nSessions:")
            for session in pending_sessions:
                print(f"\n  [{session['id']}] PENDING - {session['profile']} profile")
                print(f"    Domains: {', '.join(session['domains'])}")
                print(f"    Wait time: {session['wait_minutes']} minutes")
                
            for session in active_sessions:
                remaining = int((session['end_at'] - datetime.now()).total_seconds() / 60)
                print(f"\n  [{session['id']}] ACTIVE - {session['profile']} profile")
                print(f"    Domains: {', '.join(session['domains'])}")
                print(f"    Remaining: {remaining} minutes")
    
    def unblock(self, targets, profile_name=None):
        """Unblock domains with timing rules"""
        if not profile_name:
            profile_name = self.config_manager.get_default_profile()
            
        if not self.config_manager.is_valid_profile(profile_name):
            print(f"Error: Invalid profile '{profile_name}'")
            sys.exit(1)
            
        # Check cooldown
        timing = self.config_manager.calculate_timing(profile_name, targets)
        if not self.db.check_cooldown(profile_name, timing['cooldown']):
            print(f"Error: Profile '{profile_name}' is on cooldown")
            sys.exit(1)
            
        # Resolve targets to domains
        resolved = self.config_manager.resolve_domains(targets)
        if not resolved:
            print("Error: No valid domains to unblock")
            sys.exit(1)
            
        # Create session
        session_id = self.db.create_session(
            profile=profile_name,
            domains=resolved,
            wait_minutes=timing['wait'],
            duration_minutes=timing['duration']
        )
        
        # Update cooldown
        self.db.update_cooldown(profile_name)
        
        # Update JSON for Network Extension
        self._write_domains_for_extension()
        
        print(f"Unblock session created: {session_id}")
        print(f"Profile: {profile_name}")
        print(f"Domains: {', '.join(resolved)}")
        print(f"Wait time: {timing['wait']} minutes")
        print(f"Duration: {timing['duration']} minutes")
        
    def block_all(self):
        """Block all domains immediately"""
        # Cancel all sessions
        active = self.db.get_active_sessions()
        for session in active:
            self.db.cancel_session(session['id'])
            
        print(f"Cancelled {len(active)} active sessions")
        
        # Update JSON for Network Extension
        self._write_domains_for_extension()
        
        print("All domains are now blocked")
        
    def cancel(self, session_id):
        """Cancel a session"""
        if self.db.cancel_session(session_id):
            print(f"Cancelled session {session_id}")
            # Update JSON for Network Extension
            self._write_domains_for_extension()
        else:
            print(f"Error: Session {session_id} not found or already completed")
            sys.exit(1)
            
    def _process_expired_sessions(self):
        """Process any expired sessions"""
        # This mimics what the daemon scheduler would do

        # Activate pending sessions that are ready
        activated = self.db.activate_pending_sessions()

        # Expire active sessions that are done
        expired = self.db.expire_sessions()

        # Update JSON if anything changed
        if activated or expired:
            self._write_domains_for_extension()


def main():
    parser = argparse.ArgumentParser(
        description='alwaysblock - Block distracting websites'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Status command
    subparsers.add_parser('status', help='Show current status')
    
    # Unblock command  
    unblock_parser = subparsers.add_parser('unblock', help='Unblock domains temporarily')
    unblock_parser.add_argument('targets', nargs='+', help='Domains, tags, or groups to unblock')
    unblock_parser.add_argument('-p', '--profile', help='Unblock profile to use')
    
    # Block-all command
    subparsers.add_parser('block-all', help='Block all domains immediately')
    
    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel an unblock session')
    cancel_parser.add_argument('session_id', help='Session ID to cancel')
    
    args = parser.parse_args()
    
    # Default to status
    if not args.command:
        args.command = 'status'
        
    cli = AlwaysBlockDirect()
    
    if args.command == 'status':
        cli.status()
    elif args.command == 'unblock':
        cli.unblock(args.targets, args.profile)
    elif args.command == 'block-all':
        cli.block_all()
    elif args.command == 'cancel':
        cli.cancel(args.session_id)


if __name__ == '__main__':
    main()