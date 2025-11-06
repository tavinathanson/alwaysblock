#!/usr/bin/env python3
"""
alwaysblock CLI - Transparent proxy version
Manages blocked domains and transparent proxy daemon
"""
import argparse
import json
import sys
import subprocess
import signal
import time
from pathlib import Path
from datetime import datetime, timedelta
import os

# Import the existing modules we'll reuse
from config_manager import ConfigManager
from db import Database
from system_proxy import SystemProxy


class AlwaysBlock:
    """AlwaysBlock CLI with transparent proxy management"""

    def __init__(self):
        # Use same paths as original
        self.config_path = Path.home() / '.config' / 'alwaysblock' / 'config.yaml'
        self.db_path = Path.home() / '.local' / 'share' / 'alwaysblock' / 'alwaysblock.db'

        # JSON file for proxy (using /tmp for easy access)
        self.json_path = Path('/tmp/alwaysblock_domains.json')

        # PID file for proxy daemon (use /tmp so both sudo and non-sudo can access)
        self.pid_file = Path('/tmp/alwaysblock_proxy.pid')

        # Initialize components
        self.config_manager = ConfigManager(str(self.config_path))
        self.config_manager.load()  # Load the config
        self.db = Database(self.db_path)
        self.system_proxy = SystemProxy(proxy_port=8905)

    def _write_domains_for_proxy(self):
        """Write current blocked domains to JSON file for transparent proxy"""
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

        # Convert to format expected by proxy
        domains_data = {
            'domains': sorted(list(expanded_blocked)),
            'expirations': {}  # Proxy doesn't use temporary blocks for now
        }

        # Write to JSON file
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_path, 'w') as f:
            json.dump(domains_data, f, indent=2)

    def _process_expired_sessions(self):
        """Check for and process expired sessions"""
        # Activate pending sessions that are ready
        self.db.activate_pending_sessions()

        # Expire active sessions that are done
        self.db.expire_sessions()

    def status(self):
        """Show current status"""
        # Process any expired sessions first
        self._process_expired_sessions()

        # Update JSON for proxy
        self._write_domains_for_proxy()

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
        print(f"")

        # Check proxy status
        proxy_running = self.is_proxy_running()
        print(f"Proxy daemon: {'🟢 Running' if proxy_running else '🔴 Stopped'}")

        # Check system proxy status
        proxy_status = self.system_proxy.get_status()
        sys_proxy_enabled = proxy_status.get('enabled', False)
        print(f"System proxy: {'🟢 Enabled' if sys_proxy_enabled else '🔴 Disabled'} ({proxy_status.get('enabled_count', 0)}/{proxy_status.get('services_count', 0)} services)")
        print(f"")

        if not proxy_running:
            print("⚠️  Proxy daemon not running. Start it with: sudo alwaysblock start-proxy")
        if not sys_proxy_enabled:
            print("⚠️  System proxy not enabled. Enable with: sudo alwaysblock enable-proxy")
        print(f"")

        if active_sessions:
            print(f"Active unblock sessions ({len(active_sessions)}):")
            for session in active_sessions:
                domains_str = ', '.join(session['domains'])
                end_at = session['end_at']
                remaining = (end_at - datetime.now()).total_seconds()
                minutes = int(remaining / 60)
                print(f"  • {domains_str} - {minutes} minutes remaining")
            print(f"")

        if pending_sessions:
            print(f"Pending unblock sessions ({len(pending_sessions)}):")
            for session in pending_sessions:
                domains_str = ', '.join(session['domains'])
                start_at = session['start_at']
                wait_time = (start_at - datetime.now()).total_seconds()
                minutes = int(wait_time / 60)
                print(f"  • {domains_str} - {minutes} minutes until accessible")
            print(f"")

    def is_proxy_running(self):
        """Check if proxy daemon is running"""
        if not self.pid_file.exists():
            return False

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())

            # Check if process is running
            os.kill(pid, 0)
            return True
        except PermissionError:
            # Process exists but owned by root - that's fine, it's running
            return True
        except (ValueError, ProcessLookupError, OSError):
            # PID file exists but process is not running
            # Try to remove it, but don't fail if we can't (permission issue)
            try:
                self.pid_file.unlink(missing_ok=True)
            except PermissionError:
                pass
            return False

    def start_proxy(self):
        """Start the transparent proxy daemon"""
        if self.is_proxy_running():
            print("Proxy is already running")
            return

        # Kill any process using the proxy port
        proxy_port = 8905
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{proxy_port}'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(['kill', '-9', pid], check=False)
                        print(f"Killed existing process on port {proxy_port} (PID: {pid})")
                    except:
                        pass
                time.sleep(0.5)
        except:
            pass

        # Write current domains
        self._write_domains_for_proxy()

        # Start proxy in background
        proxy_script = Path(__file__).parent / 'http_proxy.py'

        # Log file for debugging
        log_file = self.pid_file.parent / 'proxy.log'
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Start as daemon with logging
        with open(log_file, 'a') as log:
            process = subprocess.Popen(
                [sys.executable, str(proxy_script)],
                stdout=log,
                stderr=log,
                start_new_session=True
            )

        # Write PID file (make it world-readable/writable so status command works)
        with open(self.pid_file, 'w') as f:
            f.write(str(process.pid))
        os.chmod(self.pid_file, 0o666)

        # Give it a moment to start
        time.sleep(1.0)

        if self.is_proxy_running():
            print(f"✅ Proxy started (PID: {process.pid})")
            print(f"   Logs: {log_file}")
        else:
            print("❌ Failed to start proxy")
            print(f"   Check logs: {log_file}")
            # Show last few lines of log
            if log_file.exists():
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        print("\nLast error:")
                        print(''.join(lines[-10:]))

    def stop_proxy(self):
        """Stop the transparent proxy daemon"""
        if not self.pid_file.exists():
            print("Proxy is not running")
            return

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())

            # Send SIGTERM
            os.kill(pid, signal.SIGTERM)

            # Wait for it to stop
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    break

            # Remove PID file
            self.pid_file.unlink(missing_ok=True)

            print("✅ Proxy stopped")

        except (ValueError, ProcessLookupError) as e:
            self.pid_file.unlink(missing_ok=True)
            print(f"Proxy was not running")

    def enable_system_proxy(self):
        """Enable system-wide HTTP/HTTPS proxy"""
        print("Enabling system proxy...")
        self.system_proxy.enable_proxy()

    def disable_system_proxy(self):
        """Disable system-wide HTTP/HTTPS proxy"""
        print("Disabling system proxy...")
        self.system_proxy.disable_proxy()

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

        # Update JSON for proxy
        self._write_domains_for_proxy()

        print(f"Unblock session created: {session_id}")
        print(f"Profile: {profile_name}")
        print(f"Domains: {', '.join(resolved)}")
        print(f"Wait time: {timing['wait']} minutes")
        print(f"Duration: {timing['duration']} minutes")

    def block_all(self):
        """Block all domains immediately"""
        # Cancel all sessions
        active = self.db.get_active_sessions()
        pending = self.db.get_pending_sessions()

        for session in active + pending:
            self.db.cancel_session(session['id'])

        print(f"Cancelled {len(active) + len(pending)} sessions")

        # Update JSON for proxy
        self._write_domains_for_proxy()

        print("All domains are now blocked")

    def cancel(self, session_id):
        """Cancel a session"""
        if self.db.cancel_session(session_id):
            print(f"Cancelled session {session_id}")
            # Update JSON for proxy
            self._write_domains_for_proxy()
        else:
            print(f"Error: Session {session_id} not found or already completed")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='AlwaysBlock - Website blocker with transparent proxy')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Status command
    subparsers.add_parser('status', help='Show current status')

    # Proxy daemon management
    subparsers.add_parser('start-proxy', help='Start transparent proxy daemon')
    subparsers.add_parser('stop-proxy', help='Stop transparent proxy daemon')
    subparsers.add_parser('restart-proxy', help='Restart transparent proxy daemon')

    # System proxy management
    subparsers.add_parser('enable-proxy', help='Enable system-wide proxy (requires sudo)')
    subparsers.add_parser('disable-proxy', help='Disable system-wide proxy (requires sudo)')

    # Unblock command
    unblock_parser = subparsers.add_parser('unblock', help='Temporarily unblock domains')
    unblock_parser.add_argument('targets', nargs='+', help='Domains, tags, or groups to unblock')
    unblock_parser.add_argument('-p', '--profile', help='Profile to use for unblocking')

    # Block all command
    subparsers.add_parser('block-all', help='Block all domains immediately')

    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel an unblock session')
    cancel_parser.add_argument('session_id', type=int, help='Session ID to cancel')

    args = parser.parse_args()

    # Default to status if no command
    if not args.command:
        args.command = 'status'

    ab = AlwaysBlock()

    if args.command == 'status':
        ab.status()
    elif args.command == 'start-proxy':
        ab.start_proxy()
    elif args.command == 'stop-proxy':
        ab.stop_proxy()
    elif args.command == 'restart-proxy':
        ab.stop_proxy()
        time.sleep(0.5)
        ab.start_proxy()
    elif args.command == 'enable-proxy':
        ab.enable_system_proxy()
    elif args.command == 'disable-proxy':
        ab.disable_system_proxy()
    elif args.command == 'block-all':
        ab.block_all()
    elif args.command == 'unblock':
        ab.unblock(args.targets, args.profile)
    elif args.command == 'cancel':
        ab.cancel(args.session_id)


if __name__ == '__main__':
    main()
