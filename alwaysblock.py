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
import shutil

# Import the existing modules we'll reuse
from config_manager import ConfigManager
from db import Database
from system_proxy import SystemProxy


def format_time_remaining(seconds):
    """Format time remaining, showing seconds when < 3 minutes"""
    if seconds < 180:  # Less than 3 minutes
        return f"{int(seconds)} seconds"
    else:
        return f"{int(seconds / 60)} minutes"


def session_display_name(session):
    """Human label for a session: the requested target, or its domains."""
    return session.get('target_name') or ', '.join(session['domains'])


class AlwaysBlock:
    """AlwaysBlock CLI with transparent proxy management"""

    def __init__(self):
        # Use same paths as original
        self.config_path = Path.home() / '.config' / 'alwaysblock' / 'config.yaml'
        self.db_path = Path.home() / '.local' / 'share' / 'alwaysblock' / 'alwaysblock.db'

        # Shared state file read by the proxy (and served by the bridge). Path is
        # overridable via env so tests / alternate setups can isolate it; it
        # defaults to the historical location so production is unchanged.
        self.json_path = Path(os.environ.get(
            'ALWAYSBLOCK_STATE_FILE', '/tmp/alwaysblock_domains.json'))

        # PID file for proxy daemon (use /tmp so both sudo and non-sudo can access)
        self.pid_file = Path('/tmp/alwaysblock_proxy.pid')
        self.session_manager_pid_file = Path('/tmp/alwaysblock_session_manager.pid')

        # Chrome-extension bridge (loopback HTTP, no sudo). The proxy and the
        # bridge are independent backends; either or both can run.
        self.bridge_pid_file = Path('/tmp/alwaysblock_bridge.pid')
        self.bridge_host = '127.0.0.1'
        self.bridge_port = 8906

        # Opt-in app watchdog (quits native apps while their sites are blocked).
        # Like the bridge, it runs as the user (no sudo). Off unless config has
        # a `kill_apps:` block.
        self.watchdog_pid_file = Path('/tmp/alwaysblock_watchdog.pid')

        # Initialize components
        self.db = Database(self.db_path)
        self.config_manager = ConfigManager(str(self.config_path), db=self.db)
        self.config_manager.load()  # Load the config
        self.system_proxy = SystemProxy(proxy_port=8905)

    def _write_state(self, write_file=True):
        """Compute the current blocking state and return it as a dict.

        With write_file=True (the default, used by the CLI and the proxy-side
        writers) the blob is also written to the shared state file the proxy
        watches. The bridge passes write_file=False — it only needs the dict to
        serve over HTTP and shouldn't write the proxy's file on every poll.

        This is the single seam between the brain (config + sessions + timing)
        and every enforcement backend. Both backends read this exact blob:
          - the transparent proxy (http_proxy.py) watches the file by mtime;
          - the Chrome extension's bridge (bridge.py) serves it over loopback.

        Neither backend re-derives blocking logic — they only apply what is
        computed here, which is what keeps the two backends in lockstep no matter
        which one (or both) is running.

        State blob schema (schema_version 2):
          domains:           [host, ...]   currently-blocked hosts (groups expanded)
          excluded:          [host, ...]   always-allowed hosts (win over blocks)
          unblocked:         {host: end_epoch}  configured hosts temporarily allowed,
                                                with the epoch seconds they re-block
          active_sessions:   [{name, domains, end_at}]   currently-open unblocks
          pending_sessions:  [{name, domains, start_at}]  waiting out a delay
          waiting_sessions:  [{name, domains}]   queued behind another session
          pause_until:       float (optional)  blocking fully off until this epoch
                                                (manual 2-min pause or all-day disable)
          schema_version:    int

        Matching semantics (applied identically by both backends): a host is
        blocked iff it, its www-stripped form, or any parent suffix is in
        'domains' AND no such form is in 'excluded' (excluded always wins). The
        Chrome backend gets this for free from declarativeNetRequest
        'requestDomains', which matches a domain and all its subdomains.
        """
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

        # Get excluded domains from config
        excluded_domains = self.config_manager.get_excluded_domains()

        def _epoch(dt):
            try:
                return dt.timestamp()
            except AttributeError:
                return float(dt)

        # Map each temporarily-unblocked host to the epoch it re-blocks, so the
        # extension can show a countdown and set a precise re-block alarm rather
        # than waiting for the next poll.
        unblocked_until = {d: _epoch(t) for d, t in expirations.items()}

        # Per-session views so the extension can mirror `alwaysblock status`
        # (active / pending / queued), instead of showing a noisy list of every
        # expanded member domain. 'domains' is carried so the block page can tell
        # whether the page's host is covered by a given session.
        def _view(s, **extra):
            return {'name': session_display_name(s), 'domains': s['domains'], **extra}

        active_session_view = sorted(
            (_view(s, end_at=_epoch(s['end_at'])) for s in active_sessions),
            key=lambda s: s['end_at'])
        pending_session_view = sorted(
            (_view(s, start_at=_epoch(s['start_at'])) for s in self.db.get_pending_sessions()),
            key=lambda s: s['start_at'])
        waiting_session_view = [_view(s) for s in self.db.get_waiting_sessions()]

        # Backend-agnostic blocking state. 'domains'/'excluded'/'pause_until'
        # are the original proxy contract and are unchanged; everything else is
        # additive (the proxy ignores unknown keys).
        domains_data = {
            'schema_version': 2,
            'domains': sorted(list(expanded_blocked)),
            'excluded': sorted(list(excluded_domains)),
            'unblocked': unblocked_until,
            'active_sessions': active_session_view,
            'pending_sessions': pending_session_view,
            'waiting_sessions': waiting_session_view,
        }

        # Carry forward any durable pause (manual 2-min pause or all-day disable).
        # pause_until lives in the db, so every rewrite of this file must re-apply
        # it — otherwise a session expiry, daemon restart, or reboot would silently
        # wipe an active disable and blocking would turn back on.
        pause_until = self._get_pause_until()
        if pause_until > time.time():
            domains_data['pause_until'] = pause_until
        elif pause_until:
            # Expired: clear it so we don't keep checking a stale value.
            self.db.delete_setting('pause_until')

        if not write_file:
            return domains_data

        # Write to JSON file
        self.json_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically using a temp file, then move it
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(dir=self.json_path.parent, suffix='.json')
        try:
            # Write to temp file
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(domains_data, f, indent=2)

            # Set permissions on temp file before moving
            os.chmod(temp_path, 0o666)

            # If target file exists, try to replace it
            # If we can't replace it (permission error), write directly to it instead
            try:
                os.replace(temp_path, str(self.json_path))
            except PermissionError:
                # Can't replace (file owned by root), but we can write to it (666 perms)
                # Write directly instead of replacing
                try:
                    with open(self.json_path, 'w') as f:
                        json.dump(domains_data, f, indent=2)
                    # Clean up temp file since we wrote directly
                    os.unlink(temp_path)
                except Exception as write_error:
                    # Can't write either - clean up and give up. We still return
                    # the computed blob so the bridge can serve it from memory
                    # even if the on-disk file is stuck with bad permissions.
                    os.unlink(temp_path)
                    print(f"Warning: Could not update {self.json_path}: {write_error}")
                    print(f"Run 'sudo rm {self.json_path}' to reset permissions")
                    return domains_data
        except Exception as e:
            # Clean up temp file if something went wrong
            try:
                os.unlink(temp_path)
            except:
                pass
            # Only raise if it's not a permission error we already handled
            if not isinstance(e, PermissionError):
                raise e

        return domains_data

    def _process_expired_sessions(self):
        """Check for and process expired sessions"""
        # Expire active sessions that are done (do this first!)
        self.db.expire_sessions()

        # Activate waiting sessions whose domains are now free
        self.db.activate_waiting_sessions()

        # Activate pending sessions that are ready
        self.db.activate_pending_sessions()

    def status(self):
        """Show current status"""
        # Process any expired sessions first
        self._process_expired_sessions()

        # Update JSON for proxy
        self._write_state()

        active_sessions = self.db.get_active_sessions()
        pending_sessions = self.db.get_pending_sessions()
        waiting_sessions = self.db.get_waiting_sessions()
        all_configured = self.config_manager.get_all_configured_domains()

        # Collect unblocked domains from active sessions
        unblocked_domains = set()
        for session in active_sessions:
            unblocked_domains.update(session['domains'])

        # Only count domains that are actually configured (intersection)
        unblocked_configured = unblocked_domains.intersection(set(all_configured))
        blocked_count = len(all_configured) - len(unblocked_configured)

        print(f"AlwaysBlock Status")
        print(f"==================")
        print(f"Configured domains: {len(all_configured)}")
        print(f"Currently blocked: {blocked_count}")

        # Surface an active pause/disable so it's obvious blocking is off.
        pause_until = self._get_pause_until()
        if pause_until > time.time():
            until = datetime.fromtimestamp(pause_until)
            remaining = format_time_remaining(pause_until - time.time())
            print(f"⏸️  Blocking DISABLED until {until.strftime('%-I:%M %p')} ({remaining} left)")
            print(f"   Re-enable now with: alwaysblock resume")
        print(f"")

        # Which backends this machine opted into (proxy, extension, or both).
        backends = self.config_manager.get_backends()
        enabled = [name for name in ('proxy', 'extension') if backends[name]]
        print(f"Backends:     {', '.join(enabled) if enabled else 'none (nothing will block!)'}")

        # Backend A: system proxy (covers all apps/browsers, incl. Safari & Incognito)
        proxy_running = self.is_proxy_running()
        proxy_status = self.system_proxy.get_status()
        sys_proxy_enabled = proxy_status.get('enabled', False)
        if backends['proxy']:
            print(f"Proxy daemon: {'🟢 Running' if proxy_running else '🔴 Stopped'}")
            print(f"System proxy: {'🟢 Enabled' if sys_proxy_enabled else '🔴 Disabled'} ({proxy_status.get('enabled_count', 0)}/{proxy_status.get('services_count', 0)} services)")

        # Backend B: Chrome extension bridge (covers Chrome tabs only)
        bridge_running = self.is_bridge_running()
        if backends['extension']:
            print(f"Ext. bridge:  {'🟢 Running' if bridge_running else '🔴 Stopped'} ({self.bridge_host}:{self.bridge_port})")

        # Opt-in app watchdog (only shown when configured)
        kill_apps = self.config_manager.get_kill_apps()
        watchdog_running = self.is_watchdog_running() if kill_apps else False
        if kill_apps:
            apps_label = ', '.join(e['app'] for e in kill_apps)
            print(f"App watchdog: {'🟢 Running' if watchdog_running else '🔴 Stopped'} (quits: {apps_label})")

        # Check auto-start status
        autostart_enabled = Path("/Library/LaunchDaemons/com.alwaysblock.daemon.plist").exists()
        print(f"Auto-start:   {'🟢 Enabled' if autostart_enabled else '🔴 Disabled'}")
        print(f"")

        if backends['proxy'] and not proxy_running:
            print("⚠️  Proxy daemon not running. Start it with: alwaysblock start")
        if backends['proxy'] and not sys_proxy_enabled:
            print("⚠️  System proxy not enabled. Enable with: alwaysblock start")
        if backends['extension'] and not bridge_running:
            print("⚠️  Extension bridge not running. Start it with: alwaysblock bridge start")
        if kill_apps and not watchdog_running:
            print("⚠️  App watchdog not running. Start it with: alwaysblock watchdog start")
        print(f"")

        if active_sessions:
            print(f"Active unblock sessions ({len(active_sessions)}):")
            for session in active_sessions:
                # Use target_name if available, otherwise show all domains
                display_name = session_display_name(session)
                end_at = session['end_at']
                remaining = (end_at - datetime.now()).total_seconds()
                time_str = format_time_remaining(remaining)
                print(f"  #{session['id']}: {display_name} - {time_str} remaining")
            print(f"")

        if pending_sessions:
            print(f"Pending unblock sessions ({len(pending_sessions)}):")
            for session in pending_sessions:
                # Use target_name if available, otherwise show all domains
                display_name = session_display_name(session)
                start_at = session['start_at']
                wait_time = (start_at - datetime.now()).total_seconds()
                time_str = format_time_remaining(wait_time)
                print(f"  #{session['id']}: {display_name} - {time_str} until accessible")
            print(f"")

        if waiting_sessions:
            print(f"Queued (waiting for domain to be free) ({len(waiting_sessions)}):")
            for session in waiting_sessions:
                # Use target_name if available, otherwise show all domains
                display_name = session_display_name(session)
                print(f"  #{session['id']}: {display_name} - timing will be calculated when domain becomes available")
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

    def is_session_manager_running(self):
        """Check if session manager daemon is running"""
        if not self.session_manager_pid_file.exists():
            return False

        try:
            with open(self.session_manager_pid_file, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, OSError, PermissionError):
            try:
                self.session_manager_pid_file.unlink(missing_ok=True)
            except:
                pass
            return False

    # ------------------------------------------------------------------
    # Chrome-extension bridge (backend B)
    #
    # A tiny loopback HTTP server (bridge.py) that exposes the same brain the
    # CLI uses to the Chrome extension. It runs as the user (no sudo, no system
    # changes) and is normally supervised by a per-user LaunchAgent; these
    # methods exist so it can also be driven by hand for testing.
    # ------------------------------------------------------------------
    def is_bridge_running(self):
        """Check if the bridge is listening on its loopback port."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex((self.bridge_host, self.bridge_port)) == 0

    def run_bridge(self):
        """Run the bridge in the foreground (used by the LaunchAgent)."""
        from bridge import serve
        serve(host=self.bridge_host, port=self.bridge_port)

    def start_bridge(self):
        """Start the bridge as a background daemon (manual use)."""
        if self.is_bridge_running():
            print(f"Bridge is already running on {self.bridge_host}:{self.bridge_port}")
            return

        bridge_script = Path(__file__).parent / 'bridge.py'
        log_file = self.bridge_pid_file.parent / 'bridge.log'
        log_file.touch(exist_ok=True)
        try:
            os.chmod(log_file, 0o666)
        except PermissionError:
            pass

        with open(log_file, 'a') as log:
            process = subprocess.Popen(
                [sys.executable, str(bridge_script)],
                stdout=log,
                stderr=log,
                start_new_session=True
            )

        with open(self.bridge_pid_file, 'w') as f:
            f.write(str(process.pid))
        try:
            os.chmod(self.bridge_pid_file, 0o666)
        except PermissionError:
            pass

        time.sleep(1.0)
        if self.is_bridge_running():
            print(f"✅ Bridge started (PID: {process.pid}) on {self.bridge_host}:{self.bridge_port}")
            print(f"   Logs: {log_file}")
        else:
            print("❌ Failed to start bridge")
            print(f"   Check logs: {log_file}")

    def stop_bridge(self):
        """Stop the background bridge daemon."""
        if not self.bridge_pid_file.exists():
            # Nothing we started; it may be under the LaunchAgent instead.
            if self.is_bridge_running():
                print("Bridge is running but not under our PID file "
                      "(likely the LaunchAgent). Stop it with: "
                      "launchctl unload ~/Library/LaunchAgents/com.alwaysblock.bridge.plist")
            else:
                print("Bridge is not running")
            return
        try:
            with open(self.bridge_pid_file, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.bridge_pid_file.unlink(missing_ok=True)
            print("✅ Bridge stopped")
        except (ValueError, OSError):
            self.bridge_pid_file.unlink(missing_ok=True)
            print("Bridge was not running")

    def bridge(self, action='status'):
        """Control the bridge: run (foreground) | start | stop | status."""
        if action == 'run':
            self.run_bridge()
        elif action == 'start':
            self.start_bridge()
        elif action == 'stop':
            self.stop_bridge()
        else:  # status
            running = self.is_bridge_running()
            print(f"Bridge: {'🟢 Running' if running else '🔴 Stopped'} "
                  f"({self.bridge_host}:{self.bridge_port})")
            if not running:
                print("   Start it with: alwaysblock bridge start")

    # ------------------------------------------------------------------
    # App watchdog (opt-in)
    #
    # Quits native apps (e.g. Slack) while their sites are blocked, so a blocked
    # app gives a clear signal instead of silently failing. Off by default;
    # active only when config.yaml has a `kill_apps:` block. Runs as the user
    # (no sudo), normally under a per-user LaunchAgent, mirroring the bridge.
    # ------------------------------------------------------------------
    def is_watchdog_running(self):
        """Check whether a watchdog process is running (manual or LaunchAgent).

        Matches both shapes the loop can run as: the LaunchAgent/manual CLI
        (`.../alwaysblock.py watchdog run`) and a directly-launched script
        (`python .../watchdog.py`). Deliberately does NOT match a `watchdog
        status`/`start` invocation, so this check never sees itself.
        """
        try:
            return subprocess.run(
                ['pgrep', '-f', r'alwaysblock.*watchdog run|watchdog\.py'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode == 0
        except Exception:
            return False

    def run_watchdog(self):
        """Run the watchdog loop in the foreground (used by the LaunchAgent)."""
        from watchdog import serve
        serve()

    def start_watchdog(self):
        """Start the watchdog as a background daemon (manual use)."""
        if not self.config_manager.get_kill_apps():
            print("No apps configured to watch. Add a 'kill_apps:' block to "
                  f"{self.config_path} first (see README).")
            return
        if self.is_watchdog_running():
            print("Watchdog is already running")
            return

        watchdog_script = Path(__file__).parent / 'watchdog.py'
        log_file = Path('/tmp/alwaysblock_watchdog.log')
        log_file.touch(exist_ok=True)
        try:
            os.chmod(log_file, 0o666)
        except PermissionError:
            pass

        with open(log_file, 'a') as log:
            process = subprocess.Popen(
                [sys.executable, str(watchdog_script)],
                stdout=log,
                stderr=log,
                start_new_session=True
            )

        with open(self.watchdog_pid_file, 'w') as f:
            f.write(str(process.pid))
        try:
            os.chmod(self.watchdog_pid_file, 0o666)
        except PermissionError:
            pass

        print(f"✅ Watchdog started (PID: {process.pid})")
        print(f"   Logs: {log_file}")

    def stop_watchdog(self):
        """Stop the background watchdog daemon."""
        if not self.watchdog_pid_file.exists():
            if self.is_watchdog_running():
                print("Watchdog is running but not under our PID file "
                      "(likely the LaunchAgent). Stop it with: "
                      "launchctl unload ~/Library/LaunchAgents/com.alwaysblock.watchdog.plist")
            else:
                print("Watchdog is not running")
            return
        try:
            with open(self.watchdog_pid_file, 'r') as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            self.watchdog_pid_file.unlink(missing_ok=True)
            print("✅ Watchdog stopped")
        except (ValueError, OSError):
            self.watchdog_pid_file.unlink(missing_ok=True)
            print("Watchdog was not running")

    def watchdog(self, action='status'):
        """Control the app watchdog: run (foreground) | start | stop | status."""
        if action == 'run':
            self.run_watchdog()
        elif action == 'start':
            self.start_watchdog()
        elif action == 'stop':
            self.stop_watchdog()
        else:  # status
            apps = self.config_manager.get_kill_apps()
            if not apps:
                print("App watchdog: not configured (no 'kill_apps:' in config)")
                return
            running = self.is_watchdog_running()
            print(f"App watchdog: {'🟢 Running' if running else '🔴 Stopped'}")
            for entry in apps:
                blocked = any(self.config_manager.is_domain_blocked(d) for d in entry['domains'])
                if self._get_pause_until() > time.time():
                    blocked = False
                print(f"  {entry['app']}: {'🔴 blocked (will be quit)' if blocked else '🟢 allowed'}")
            if not running:
                print("   Start it with: alwaysblock watchdog start")

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
                    # Validate PID is numeric before killing
                    if not pid.strip().isdigit():
                        continue
                    try:
                        subprocess.run(['sudo', 'kill', '-9', pid.strip()], check=False)
                        print(f"Killed existing process on port {proxy_port} (PID: {pid})")
                    except:
                        pass
                time.sleep(0.5)
        except:
            pass

        # Also check for stale http_proxy.py processes (might be running as root)
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'http_proxy.py'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    # Validate PID is numeric before killing
                    if not pid.strip().isdigit():
                        continue
                    try:
                        subprocess.run(['sudo', 'kill', '-9', pid.strip()], check=False)
                        print(f"Killed stale proxy process (PID: {pid})")
                    except:
                        pass
                time.sleep(0.5)
        except:
            pass

        # Also check for stale session_manager.py processes (might be running as root)
        try:
            result = subprocess.run(
                ['pgrep', '-f', 'session_manager.py'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    # Validate PID is numeric before killing
                    if not pid.strip().isdigit():
                        continue
                    try:
                        subprocess.run(['sudo', 'kill', '-9', pid.strip()], check=False)
                        print(f"Killed stale session manager process (PID: {pid})")
                    except:
                        pass
                time.sleep(0.5)
        except:
            pass

        # Clean up stale PID files (might be left over if stop couldn't remove them)
        for pid_file in [self.pid_file, self.session_manager_pid_file]:
            if pid_file.exists():
                try:
                    pid_file.unlink()
                except PermissionError:
                    # Can't remove, will try again later
                    pass

        # Write current domains
        self._write_state()

        # Start proxy in background
        proxy_script = Path(__file__).parent / 'http_proxy.py'

        # Log file for debugging
        log_file = self.pid_file.parent / 'proxy.log'
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Ensure log file exists and has correct permissions
        log_file.touch(exist_ok=True)
        try:
            os.chmod(log_file, 0o666)
        except PermissionError:
            # Can't chmod (file owned by root), but we can write to it
            pass

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
        try:
            os.chmod(self.pid_file, 0o666)
        except PermissionError:
            # Can't chmod (file owned by root), but we can write to it
            pass

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
            return

        # Start session manager daemon
        if not self.is_session_manager_running():
            session_manager_script = Path(__file__).parent / 'session_manager.py'
            sm_log_file = self.session_manager_pid_file.parent / 'session_manager.log'

            # Ensure log file exists and has correct permissions
            sm_log_file.touch(exist_ok=True)
            try:
                os.chmod(sm_log_file, 0o666)
            except PermissionError:
                # Can't chmod (file owned by root), but we can write to it
                pass

            with open(sm_log_file, 'a') as log:
                sm_process = subprocess.Popen(
                    [sys.executable, str(session_manager_script)],
                    stdout=log,
                    stderr=log,
                    start_new_session=True
                )

            with open(self.session_manager_pid_file, 'w') as f:
                f.write(str(sm_process.pid))
            try:
                os.chmod(self.session_manager_pid_file, 0o666)
            except PermissionError:
                # Can't chmod (file owned by root), but we can write to it
                pass

            print(f"✅ Session manager started (PID: {sm_process.pid})")

    def stop_proxy(self):
        """Stop the transparent proxy daemon"""
        # Stop session manager first
        if self.session_manager_pid_file.exists():
            try:
                with open(self.session_manager_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, signal.SIGTERM)
                except PermissionError:
                    # Process owned by root, use sudo
                    subprocess.run(['sudo', 'kill', '-TERM', str(pid)], check=False)
                try:
                    self.session_manager_pid_file.unlink(missing_ok=True)
                except PermissionError:
                    # PID file owned by root, leave it
                    pass
                print("✅ Session manager stopped")
            except PermissionError:
                # Can't read PID file - probably doesn't exist or wrong perms
                pass
            except Exception:
                try:
                    self.session_manager_pid_file.unlink(missing_ok=True)
                except:
                    pass

        # Stop proxy
        if not self.pid_file.exists():
            print("Proxy is not running")
            return

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())

            # Send SIGTERM
            try:
                os.kill(pid, signal.SIGTERM)
            except PermissionError:
                # Process owned by root, use sudo
                subprocess.run(['sudo', 'kill', '-TERM', str(pid)], check=False)

            # Wait for it to stop
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    break

            # Remove PID file
            try:
                self.pid_file.unlink(missing_ok=True)
            except PermissionError:
                # PID file owned by root, leave it - will be cleaned up next start
                pass

            print("✅ Proxy stopped")

        except (ValueError, ProcessLookupError) as e:
            try:
                self.pid_file.unlink(missing_ok=True)
            except PermissionError:
                pass
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
        """Unblock domains with timing rules

        Each target creates a separate session that queues sequentially.
        For example: 'unblock gmail slack facebook' creates 3 sessions,
        each waiting for the previous one to complete before starting.

        If targets is empty, unblocks ALL configured domains.
        """
        if not profile_name:
            profile_name = self.config_manager.get_default_profile()

        if not self.config_manager.is_valid_profile(profile_name):
            print(f"Error: Invalid profile '{profile_name}'")
            sys.exit(1)

        # Validate target_type constraint
        target_type = self.config_manager.get_profile_target_type(profile_name)
        if target_type == 'all' and targets:
            print(f"Error: Profile '{profile_name}' applies to all domains and doesn't accept targets")
            sys.exit(1)
        if target_type == 'single':
            if not targets:
                print(f"Error: Profile '{profile_name}' requires exactly one target")
                sys.exit(1)
            if len(targets) > 1:
                print(f"Error: Profile '{profile_name}' only accepts a single target, got {len(targets)}")
                sys.exit(1)

        # If no targets specified, use all configured domains
        if not targets:
            all_domains = self.config_manager.get_all_configured_domains()
            if not all_domains:
                print("Error: No domains configured")
                sys.exit(1)
            # Create a single session with all domains
            targets = ['__ALL__']  # Special marker
            all_resolved = [('all domains', all_domains)]
            all_invalid = []
        else:
            # Validate all targets first
            all_resolved = []
            all_invalid = []

            for target in targets:
                resolved, invalid = self.config_manager.resolve_domains([target])
                if resolved:
                    all_resolved.append((target, resolved))
                if invalid:
                    all_invalid.extend(invalid)

        # Show error for invalid targets
        if all_invalid:
            print(f"Error: The following targets are not in your configuration:")
            for target in all_invalid:
                print(f"  - {target}")
            print(f"\nValid targets are domain names or groups from your config.yaml")
            print(f"Hint: You can try just the domain name (e.g., 'youtube' instead of 'youtube.com')")
            sys.exit(1)

        if not all_resolved:
            print("Error: No valid domains to unblock")
            sys.exit(1)

        # Check cooldown once at the start
        # Use the first target for timing calculation (they should all use same profile anyway)
        timing = self.config_manager.calculate_timing(profile_name, [targets[0]])
        if not self.db.check_cooldown(profile_name, timing['cooldown']):
            print(f"Error: Profile '{profile_name}' is on cooldown")
            sys.exit(1)

        # Update cooldown once
        self.db.update_cooldown(profile_name)

        # Create separate sessions for each target
        # Each session is independent and only queues if the same domain is already active/pending
        session_ids = []
        print(f"Creating {len(all_resolved)} unblock session(s)...\n")

        for target, domains in all_resolved:
            # Calculate timing for this specific target
            timing = self.config_manager.calculate_timing(profile_name, [target])

            # For non-independent immediate access profiles (wait=0), cancel overlapping sessions
            # Independent profiles (like bypass/quick) run concurrently without affecting others
            is_independent = self.config_manager.is_profile_independent(profile_name)
            if timing['wait'] == 0 and not is_independent:
                all_sessions = (self.db.get_active_sessions() +
                               self.db.get_pending_sessions() +
                               self.db.get_waiting_sessions())

                domains_set = set(domains)
                for session in all_sessions:
                    session_domains = set(session['domains'])
                    if domains_set & session_domains:  # If any overlap
                        self.db.cancel_session(session['id'])
                        display_name = session_display_name(session)
                        print(f"Cancelled overlapping session #{session['id']}: {display_name}")

            # Create session - it will automatically queue if these domains are already active/pending
            # Independent sessions never queue and run concurrently with other sessions
            session_id = self.db.create_session(
                profile=profile_name,
                domains=domains,
                wait_minutes=timing['wait'],
                duration_minutes=timing['duration'],
                has_override=timing['has_override'],
                target_name=target,
                independent=is_independent
            )

            session_ids.append(session_id)

            # Get session details to show timing
            all_sessions = self.db.get_pending_sessions() + self.db.get_active_sessions() + self.db.get_waiting_sessions()
            session = next(s for s in all_sessions if s['id'] == session_id)

            print(f"Session {session_id}: {target}")

            if session['status'] == 'waiting_for_domain':
                # Waiting sessions don't have start/end times yet
                print(f"  Status: Queued (waiting for domain to become available)")
                print(f"  Duration: {timing['duration']} minutes")
                print(f"  Note: Wait time will be calculated when domain becomes free")
            else:
                # Pending/active sessions have calculated times
                now = datetime.now()
                wait_time = (session['start_at'] - now).total_seconds()

                print(f"  Wait: {format_time_remaining(wait_time)} ({timing['explanation']})")
                print(f"  Duration: {timing['duration']} minutes")
                print(f"  Start at: {session['start_at'].strftime('%-I:%M:%S %p')}")
                print(f"  End at: {session['end_at'].strftime('%-I:%M:%S %p')}")
            print()

        # Update JSON for proxy
        self._write_state()

        if len(session_ids) > 1:
            print(f"✅ Created {len(session_ids)} queued sessions")
        else:
            print(f"✅ Created 1 session")

    def _get_pause_until(self):
        """Return the durable pause-until timestamp (0.0 if unset/unparseable)"""
        raw = self.db.get_setting('pause_until')
        if not raw:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    def _set_pause_until(self, pause_until):
        """Persist the pause-until timestamp durably and push it to the proxy"""
        self.db.set_setting('pause_until', repr(float(pause_until)))
        # _write_state reads pause_until back from the db and writes
        # it into the proxy's JSON, so blocking turns off immediately.
        self._write_state()

    def pause(self):
        """Manually pause blocking for 2 minutes (fallback if auto-detection doesn't work)"""
        self._set_pause_until(time.time() + 120)  # 2 minutes from now
        print("✅ Blocking paused for 2 minutes")
        print("   Run 'alwaysblock resume' to restore blocking immediately")

    def disable(self):
        """Disable blocking for the rest of the day (until local midnight).

        Intended for travel / hotspots where blocking gets in the way. Unlike the
        2-minute pause, this is durable: it survives session expiry, daemon
        restarts, and reboots, so blocking won't quietly turn back on before
        midnight. Run 'alwaysblock resume' to re-enable early.
        """
        now = datetime.now()
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._set_pause_until(midnight.timestamp())
        print(f"✅ Blocking disabled until midnight ({midnight.strftime('%-I:%M %p')})")
        print(f"   That's {format_time_remaining((midnight - now).total_seconds())} from now")
        print("   Run 'alwaysblock resume' to re-enable blocking now")

    def resume(self):
        """Resume blocking after a manual pause or all-day disable"""
        self.db.delete_setting('pause_until')
        self._write_state()
        print("✅ Blocking resumed")

    def block_all(self):
        """Block all domains immediately"""
        # Cancel all sessions (active, pending, and waiting)
        active = self.db.get_active_sessions()
        pending = self.db.get_pending_sessions()
        waiting = self.db.get_waiting_sessions()

        for session in active + pending + waiting:
            self.db.cancel_session(session['id'])

        total = len(active) + len(pending) + len(waiting)
        print(f"Cancelled {total} session{'s' if total != 1 else ''}")

        # Update JSON for proxy
        self._write_state()

        print("All domains are now blocked")

    def cancel(self, identifier):
        """Cancel session(s) by ID, target name, or domain

        Args:
            identifier: Can be:
                - Session ID (numeric)
                - Target name (e.g., 'slack', 'gmail')
                - Domain name (e.g., 'slack.com')
        """
        # Try to parse as session ID first
        try:
            session_id = int(identifier)
            if self.db.cancel_session(session_id):
                print(f"Cancelled session #{session_id}")
                self._write_state()
            else:
                print(f"Error: Session #{session_id} not found or already completed")
                sys.exit(1)
            return
        except ValueError:
            # Not a number, treat as target/domain name
            pass

        # Look for sessions by target name or domain
        all_sessions = (self.db.get_active_sessions() +
                       self.db.get_pending_sessions() +
                       self.db.get_waiting_sessions())

        matching_sessions = []
        for session in all_sessions:
            # Check target name match
            if session.get('target_name') == identifier:
                matching_sessions.append(session)
            # Check if identifier matches any domain in the session
            elif identifier in session['domains']:
                matching_sessions.append(session)

        if not matching_sessions:
            print(f"Error: No active sessions found for '{identifier}'")
            print(f"Hint: Use 'alwaysblock status' to see active sessions")
            sys.exit(1)

        # Cancel all matching sessions
        cancelled_count = 0
        for session in matching_sessions:
            if self.db.cancel_session(session['id']):
                display_name = session_display_name(session)
                print(f"Cancelled session #{session['id']}: {display_name}")
                cancelled_count += 1

        if cancelled_count > 0:
            self._write_state()
            if cancelled_count > 1:
                print(f"Total: {cancelled_count} sessions cancelled")
        else:
            print(f"Error: Failed to cancel sessions")
            sys.exit(1)

    def enable_autostart(self):
        """Enable auto-start on boot via LaunchDaemon"""
        script_dir = Path(__file__).parent
        plist_path = Path("/Library/LaunchDaemons/com.alwaysblock.daemon.plist")
        daemon_script = Path("/usr/local/bin/alwaysblock-daemon")
        venv_path = Path.home() / '.alwaysblock-venv'

        # Read daemon template and substitute venv path
        daemon_template = script_dir / "alwaysblock-daemon.sh"
        if not daemon_template.exists():
            print(f"Error: {daemon_template} not found")
            sys.exit(1)

        with open(daemon_template, 'r') as f:
            daemon_content = f.read()

        # Substitute __VENV_PATH__ with actual venv path
        daemon_content = daemon_content.replace('__VENV_PATH__', str(venv_path))

        try:
            with open(daemon_script, 'w') as f:
                f.write(daemon_content)
            os.chmod(daemon_script, 0o755)
        except PermissionError:
            print("Error: This command requires sudo")
            sys.exit(1)

        # Copy plist
        source_plist = script_dir / "com.alwaysblock.daemon.plist"
        if not source_plist.exists():
            print(f"Error: {source_plist} not found")
            sys.exit(1)

        subprocess.run(['cp', str(source_plist), str(plist_path)], check=True)
        subprocess.run(['chown', 'root:wheel', str(plist_path)], check=True)
        subprocess.run(['chmod', '644', str(plist_path)], check=True)

        # Load the LaunchDaemon
        subprocess.run(['launchctl', 'load', str(plist_path)], check=False)

        print("✅ Auto-start enabled")
        print("   AlwaysBlock will start automatically on boot")

    def disable_autostart(self):
        """Disable auto-start on boot"""
        plist_path = Path("/Library/LaunchDaemons/com.alwaysblock.daemon.plist")
        daemon_script = Path("/usr/local/bin/alwaysblock-daemon")

        if not plist_path.exists():
            print("Auto-start is not currently enabled")
            return

        # Unload the LaunchDaemon
        subprocess.run(['launchctl', 'unload', str(plist_path)], check=False)

        # Remove files
        try:
            plist_path.unlink(missing_ok=True)
            daemon_script.unlink(missing_ok=True)
        except PermissionError:
            print("Error: This command requires sudo")
            sys.exit(1)

        print("✅ Auto-start disabled")
        print("   AlwaysBlock will no longer start automatically on boot")

    def uninstall(self, remove_data=False):
        """Uninstall AlwaysBlock"""
        print("AlwaysBlock Uninstall")
        print("====================")
        print("")

        # Unload and remove LaunchDaemon if it exists
        plist_path = Path("/Library/LaunchDaemons/com.alwaysblock.daemon.plist")
        if plist_path.exists():
            print("Removing auto-start LaunchDaemon...")
            subprocess.run(['launchctl', 'unload', str(plist_path)], check=False, stderr=subprocess.DEVNULL)
            try:
                plist_path.unlink(missing_ok=True)
            except PermissionError:
                print("Error: Cannot remove LaunchDaemon (requires sudo)")
                sys.exit(1)

        # Unload and remove per-user LaunchAgents (bridge + opt-in watchdog).
        # These run as the user, so no sudo is needed to tear them down.
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        for agent_name in ("com.alwaysblock.bridge.plist", "com.alwaysblock.watchdog.plist"):
            agent_plist = agents_dir / agent_name
            if agent_plist.exists():
                print(f"Removing LaunchAgent {agent_name}...")
                subprocess.run(['launchctl', 'unload', str(agent_plist)],
                               check=False, stderr=subprocess.DEVNULL)
                agent_plist.unlink(missing_ok=True)

        # Remove daemon script
        daemon_script = Path("/usr/local/bin/alwaysblock-daemon")
        if daemon_script.exists():
            try:
                daemon_script.unlink()
            except PermissionError:
                print("Error: Cannot remove daemon script (requires sudo)")
                sys.exit(1)

        # Remove passwordless sudo configuration
        sudoers_file = Path("/etc/sudoers.d/alwaysblock")
        if sudoers_file.exists():
            print("Removing passwordless sudo configuration...")
            try:
                sudoers_file.unlink()
            except PermissionError:
                print("Error: Cannot remove sudoers file (requires sudo)")
                sys.exit(1)

        # Stop proxy if running
        print("Stopping proxy daemon...")
        self.stop_proxy()

        print("Disabling system proxy...")
        self.disable_system_proxy()

        # Kill any processes on port 8905
        try:
            result = subprocess.run(
                ['lsof', '-ti', ':8905'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    # Validate PID is numeric before killing
                    if not pid.strip().isdigit():
                        continue
                    subprocess.run(['kill', '-9', pid.strip()], check=False, stderr=subprocess.DEVNULL)
                print("Killed remaining proxy processes...")
        except:
            pass

        # Remove CLI
        cli_path = Path("/usr/local/bin/alwaysblock")
        if cli_path.exists():
            print("Removing CLI...")
            try:
                cli_path.unlink()
            except PermissionError:
                print("Error: Cannot remove CLI (requires sudo)")
                sys.exit(1)

        # Remove PF rules (legacy cleanup)
        pf_anchor = Path("/etc/pf.anchors/com.alwaysblock")
        if pf_anchor.exists():
            print("Removing PF rules...")
            try:
                pf_anchor.unlink()
            except PermissionError:
                pass

        pf_conf = Path("/etc/pf.conf")
        if pf_conf.exists():
            try:
                with open(pf_conf, 'r') as f:
                    content = f.read()
                if 'com.alwaysblock' in content or 'AlwaysBlock' in content:
                    print("Cleaning PF configuration...")
                    # Note: Would need sudo to modify pf.conf
                    print("Warning: You may need to manually clean /etc/pf.conf")
            except:
                pass

        # Remove old Network Extension if exists (legacy cleanup)
        old_app = Path("/Applications/AlwaysBlock.app")
        if old_app.exists():
            print("Removing old Network Extension app...")
            try:
                shutil.rmtree(old_app)
            except Exception as e:
                print(f"Warning: Could not remove {old_app}: {e}")

        if remove_data:
            print("Removing configuration and data...")
            config_dir = Path.home() / '.config' / 'alwaysblock'
            data_dir = Path.home() / '.local' / 'share' / 'alwaysblock'
            venv_dir = Path.home() / '.alwaysblock-venv'

            for dir_path in [config_dir, data_dir, venv_dir]:
                if dir_path.exists():
                    try:
                        shutil.rmtree(dir_path)
                        print(f"  Removed: {dir_path}")
                    except Exception as e:
                        print(f"  Warning: Could not remove {dir_path}: {e}")

            print("Configuration and data removed.")
        else:
            print("Keeping configuration and data:")
            print("  Config: ~/.config/alwaysblock")
            print("  Data:   ~/.local/share/alwaysblock")
            print("  Venv:   ~/.alwaysblock-venv")
            print("")
            print("To remove manually: rm -rf ~/.config/alwaysblock ~/.local/share/alwaysblock ~/.alwaysblock-venv")

        print("")
        print("✅ AlwaysBlock uninstalled successfully!")
        print("")

    def upgrade(self):
        """Upgrade AlwaysBlock to latest version"""
        print("AlwaysBlock Upgrade")
        print("===================")
        print("")

        # Get script directory (repo root)
        script_dir = Path(__file__).parent

        # Check if we're in a git repo
        if not (script_dir / '.git').exists():
            print("Error: Not in a git repository")
            print("Please clone from GitHub to enable upgrades")
            sys.exit(1)

        print("Fetching latest changes...")
        already_up_to_date = False
        try:
            result = subprocess.run(
                ['git', 'pull'],
                cwd=script_dir,
                capture_output=True,
                text=True,
                check=True
            )
            print(result.stdout)

            if "Already up to date" in result.stdout:
                already_up_to_date = True
                print("✅ Already on latest version")

        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to pull latest changes")
            print(e.stderr)
            sys.exit(1)

        # Check if services were running before upgrade
        proxy_was_running = self.is_proxy_running()
        sysproxy_enabled = self.system_proxy.get_status().get('enabled', False)

        # Only run install script if there were updates
        if not already_up_to_date:
            print("Running install script to apply updates...")
            install_script = script_dir / 'install.sh'

            if not install_script.exists():
                print("Error: install.sh not found")
                sys.exit(1)

            try:
                # Run install script - it will preserve config and restart services if needed
                subprocess.run(['bash', str(install_script)], cwd=script_dir, check=True)
            except subprocess.CalledProcessError:
                print("Error: Installation failed")
                sys.exit(1)

        # Always restart services after upgrade
        print("")

        # If no changes, ask if user wants to restart
        should_restart = True
        if already_up_to_date:
            try:
                response = input("No changes detected. Restart services anyway? [Y/n]: ").strip().lower()
                should_restart = response in ['', 'y', 'yes']
            except (EOFError, KeyboardInterrupt):
                print("\nSkipping restart")
                should_restart = False

        if should_restart:
            print("Restarting services...")
            self.restart()

        print("")
        print("✅ Upgrade complete!")
        print("")

    def start(self):
        """Start the enabled AlwaysBlock backends (see config 'backends')."""
        backends = self.config_manager.get_backends()
        print("Starting AlwaysBlock services...")
        print(f"Backends: proxy={'on' if backends['proxy'] else 'off'}, "
              f"extension={'on' if backends['extension'] else 'off'}")
        print("")

        if backends['proxy']:
            self.start_proxy()
            print("")
            self.enable_system_proxy()
            print("")

        if backends['extension']:
            self.start_bridge()
            print("")

        if not backends['proxy'] and not backends['extension']:
            print("⚠️  No backends enabled in config. Set 'backends.proxy' and/or "
                  "'backends.extension' to true in ~/.config/alwaysblock/config.yaml")
            print("")

        print("✅ Done")
        print("")
        self.status()

    def stop(self):
        """Stop the enabled AlwaysBlock backends."""
        backends = self.config_manager.get_backends()
        print("Stopping AlwaysBlock services...")

        if backends['proxy']:
            self.disable_system_proxy()
            print("")
            self.stop_proxy()
            print("")

        if backends['extension']:
            self.stop_bridge()
            print("")

        print("✅ All enabled services stopped")

    def restart(self):
        """Restart all AlwaysBlock services"""
        self.stop()
        print("")
        time.sleep(1)
        self.start()

    def test(self):
        """Run test suite"""
        script_dir = Path(__file__).parent
        venv_dir = script_dir / 'venv'

        # Create venv if needed
        if not venv_dir.exists():
            print("Creating test virtual environment...")
            subprocess.run(['python3', '-m', 'venv', str(venv_dir)], check=True)

            # Install requirements
            print("Installing test dependencies...")
            pip_path = venv_dir / 'bin' / 'pip'
            requirements = script_dir / 'requirements.txt'
            subprocess.run([str(pip_path), 'install', '-r', str(requirements), '-q'], check=True)

        # Run pytest
        print("Running tests...")
        print("")
        pytest_path = venv_dir / 'bin' / 'pytest'
        result = subprocess.run([str(pytest_path)], cwd=script_dir)
        sys.exit(result.returncode)


def require_sudo():
    """Re-execute the current command with sudo if not running as root"""
    if os.geteuid() != 0:
        # Re-execute with sudo, using the same Python interpreter (venv)
        args = ['sudo', '-E', sys.executable] + sys.argv
        os.execvp('sudo', args)


def rewrite_profile_shortcut(argv, available_profiles):
    """Expand a profile-name shortcut into an explicit unblock command.

    'alwaysblock bypass reddit' -> 'alwaysblock unblock -p bypass reddit'
    'alwaysblock bypass'        -> 'alwaysblock unblock -p bypass'

    Returns argv unchanged when the first token isn't a configured profile.
    Pure function so it can be unit-tested (see tests/test_cli_shortcuts.py) —
    it used to be inline in main() and was easy to break unnoticed.
    """
    if len(argv) > 1 and argv[1] in available_profiles:
        return [argv[0], 'unblock', '-p', argv[1]] + argv[2:]
    return argv


def main():
    # Read config once, before argparse, for the two pre-dispatch decisions:
    #   - profile-name shortcuts (`alwaysblock bypass` -> `unblock -p bypass`)
    #   - whether the proxy backend is enabled, so start/stop only demand sudo
    #     when there's actually a system proxy to manage (extension-only users
    #     never get a sudo prompt; default is proxy-on, matching old behavior).
    # Reuse ConfigManager so the parsing and defaults live in exactly one place.
    available_profiles = []
    proxy_backend_enabled = True
    config_path = Path.home() / '.config' / 'alwaysblock' / 'config.yaml'
    if config_path.exists():
        try:
            cfg = ConfigManager(str(config_path))
            cfg.load()
            available_profiles = cfg.get_profile_names()
            proxy_backend_enabled = cfg.get_backends()['proxy']
        except Exception:
            pass

    # If the first arg is a profile name, rewrite to an explicit unblock command.
    sys.argv = rewrite_profile_shortcut(sys.argv, available_profiles)

    parser = argparse.ArgumentParser(description='AlwaysBlock - Website blocker with transparent proxy')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Status command
    subparsers.add_parser('status', help='Show current status')

    # Service management (high-level)
    subparsers.add_parser('start', help='Start enabled backends (see config "backends")')
    subparsers.add_parser('stop', help='Stop enabled backends')
    subparsers.add_parser('restart', help='Restart enabled backends')

    # Chrome-extension bridge control (loopback HTTP on 127.0.0.1:8906, no sudo)
    bridge_parser = subparsers.add_parser('bridge', help='Control the Chrome-extension bridge (no sudo)')
    bridge_parser.add_argument('action', nargs='?', default='status',
                               choices=['run', 'start', 'stop', 'status'],
                               help='run (foreground, for LaunchAgent) | start | stop | status')

    # App watchdog command (opt-in; quits native apps while their sites are blocked)
    watchdog_parser = subparsers.add_parser('watchdog', help='Control the opt-in app watchdog (no sudo)')
    watchdog_parser.add_argument('action', nargs='?', default='status',
                                 choices=['run', 'start', 'stop', 'status'],
                                 help='run (foreground, for LaunchAgent) | start | stop | status')

    # Unblock command
    unblock_parser = subparsers.add_parser('unblock', help='Temporarily unblock domains')
    unblock_parser.add_argument('targets', nargs='*', help='Domains, tags, or groups to unblock (default: all)')
    unblock_parser.add_argument('-p', '--profile', help='Profile to use for unblocking')

    # Block all command
    subparsers.add_parser('block-all', help='Block all domains immediately')
    subparsers.add_parser('reset', help='Cancel all unblocks (alias for block-all)')

    # Pause/resume (manual fallback for captive portal)
    subparsers.add_parser('pause', help='Manually pause blocking for 2 min (for captive portal issues)')
    subparsers.add_parser('disable', help='Disable blocking until midnight (for travel/hotspots; survives reboot)')
    subparsers.add_parser('resume', help='Resume blocking after a pause or disable')

    # Cancel command
    cancel_parser = subparsers.add_parser('cancel', help='Cancel an unblock session')
    cancel_parser.add_argument('identifier', help='Session ID, target name, or domain to cancel')

    # Auto-start management
    subparsers.add_parser('enable-autostart', help='Enable auto-start on boot (requires sudo)')
    subparsers.add_parser('disable-autostart', help='Disable auto-start on boot (requires sudo)')

    # Uninstall command
    uninstall_parser = subparsers.add_parser('uninstall', help='Uninstall AlwaysBlock (requires sudo)')
    uninstall_parser.add_argument('--remove-data', action='store_true', help='Also remove configuration and data')

    # Upgrade command
    subparsers.add_parser('upgrade', help='Upgrade to latest version from git')

    # Test command
    subparsers.add_parser('test', help='Run test suite')

    args = parser.parse_args()

    # Default to status if no command
    if not args.command:
        args.command = 'status'

    # Commands that require root. start/stop/restart only need root when the
    # proxy backend is on (it manages the system proxy via networksetup); an
    # extension-only machine runs them with no sudo. The 'bridge' command never
    # needs root. autostart/uninstall touch /Library, so they always do.
    sudo_commands = {
        'enable-autostart', 'disable-autostart',
        'uninstall'
    }
    if proxy_backend_enabled:
        sudo_commands |= {'start', 'stop', 'restart'}

    # Re-exec with sudo if needed
    if args.command in sudo_commands:
        require_sudo()

    ab = AlwaysBlock()

    if args.command == 'status':
        ab.status()
    elif args.command == 'start':
        ab.start()
    elif args.command == 'stop':
        ab.stop()
    elif args.command == 'restart':
        ab.restart()
    elif args.command == 'bridge':
        ab.bridge(args.action)
    elif args.command == 'watchdog':
        ab.watchdog(args.action)
    elif args.command == 'block-all' or args.command == 'reset':
        ab.block_all()
    elif args.command == 'pause':
        ab.pause()
    elif args.command == 'disable':
        ab.disable()
    elif args.command == 'resume':
        ab.resume()
    elif args.command == 'unblock':
        ab.unblock(args.targets, args.profile)
    elif args.command == 'cancel':
        ab.cancel(args.identifier)
    elif args.command == 'enable-autostart':
        ab.enable_autostart()
    elif args.command == 'disable-autostart':
        ab.disable_autostart()
    elif args.command == 'uninstall':
        ab.uninstall(remove_data=args.remove_data)
    elif args.command == 'upgrade':
        ab.upgrade()
    elif args.command == 'test':
        ab.test()


if __name__ == '__main__':
    main()
