#!/usr/bin/env python3
"""
HTTP/HTTPS proxy with SNI inspection for AlwaysBlock
Handles both HTTP and HTTPS CONNECT requests
"""
import socket
import select
import threading
import logging
import json
import time
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class HTTPProxy:
    """HTTP/HTTPS proxy that blocks based on hostname"""

    def __init__(self, port=8905, blocked_domains_file="/tmp/alwaysblock_domains.json"):
        self.port = port
        self.blocked_domains_file = Path(blocked_domains_file)
        self.stats_file = Path("/tmp/alwaysblock_stats.json")
        self.blocked_domains = set()
        self.stats = {}  # domain -> count
        self.last_attempt = {}  # domain -> timestamp (for rate limiting)
        self.stats_lock = threading.Lock()
        self.server_socket = None
        self.running = False
        self.last_mtime = 0

    def load_blocked_domains(self):
        """Load blocked domains from JSON file"""
        try:
            if self.blocked_domains_file.exists():
                with open(self.blocked_domains_file, 'r') as f:
                    data = json.load(f)
                    self.blocked_domains = set(data.get('domains', []))
                    self.last_mtime = self.blocked_domains_file.stat().st_mtime
                    logger.info(f"Loaded {len(self.blocked_domains)} blocked domains")
            else:
                logger.warning(f"Blocked domains file not found: {self.blocked_domains_file}")
                self.blocked_domains = set()
        except Exception as e:
            logger.error(f"Failed to load blocked domains: {e}")
            self.blocked_domains = set()

    def check_and_reload(self):
        """Check if domains file changed and reload if needed"""
        try:
            if self.blocked_domains_file.exists():
                mtime = self.blocked_domains_file.stat().st_mtime
                if mtime > self.last_mtime:
                    self.load_blocked_domains()
        except Exception as e:
            logger.debug(f"Error checking file mtime: {e}")

    def load_stats(self):
        """Load stats from JSON file"""
        try:
            if self.stats_file.exists():
                with open(self.stats_file, 'r') as f:
                    data = json.load(f)
                    with self.stats_lock:
                        self.stats = data.get('stats', {})
                    logger.info(f"Loaded stats for {len(self.stats)} domains")
            else:
                # Create empty stats file
                self.save_stats()
        except Exception as e:
            logger.error(f"Failed to load stats: {e}")
            with self.stats_lock:
                self.stats = {}

    def save_stats(self):
        """Save stats to JSON file"""
        try:
            with self.stats_lock:
                data = {'stats': self.stats}

            # Write atomically using temp file
            import tempfile
            temp_fd, temp_path = tempfile.mkstemp(dir=self.stats_file.parent, suffix='.json')
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(data, f, indent=2)

                # Set permissions
                os.chmod(temp_path, 0o666)

                # Replace existing file
                os.replace(temp_path, str(self.stats_file))
            except Exception as e:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except:
                    pass
                raise e

        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def record_blocked_attempt(self, domain: str):
        """Record a blocked attempt for a domain (only counts user-navigable domains)

        Only counts attempts to main domains (naked or www) that users actually navigate to.
        Ignores API/CDN subdomains like edge-chat.facebook.com, gateway.instagram.com, etc.
        since those are background polling, not intentional user visits.

        Also rate-limits to once per 5 minutes per domain to avoid counting page refreshes.
        """
        # Filter out API/service subdomains - only count main navigable domains
        # Skip if domain has more than one subdomain level (e.g., api.example.com, edge-chat.facebook.com)
        parts = domain.split('.')

        # Normalize: treat www.example.com same as example.com
        if parts[0] == 'www' and len(parts) >= 3:
            # www.facebook.com -> facebook.com
            normalized_domain = '.'.join(parts[1:])
        else:
            normalized_domain = domain

        # Only count if it's a root domain (example.com) or www subdomain
        # Skip multi-level subdomains like edge-chat.facebook.com
        if parts[0] != 'www' and len(parts) > 2:
            logger.debug(f"Skipping stats for API subdomain: {domain}")
            return

        now = time.time()

        with self.stats_lock:
            # Check if we've seen this domain recently (within 5 minutes)
            last_time = self.last_attempt.get(normalized_domain, 0)
            time_since_last = now - last_time

            # Only count if it's been at least 5 minutes (300 seconds)
            if time_since_last >= 300:
                self.stats[normalized_domain] = self.stats.get(normalized_domain, 0) + 1
                self.last_attempt[normalized_domain] = now
                logger.info(f"📊 Recorded blocked attempt for {normalized_domain} (count: {self.stats[normalized_domain]})")
            else:
                logger.debug(f"Ignoring duplicate attempt for {normalized_domain} ({int(time_since_last)}s since last)")

    def should_block_domain(self, hostname):
        """Check if domain should be blocked (with subdomain matching)"""
        if not hostname:
            return False

        # Direct match
        if hostname in self.blocked_domains:
            return True

        # Check without www prefix
        if hostname.startswith('www.'):
            if hostname[4:] in self.blocked_domains:
                return True

        # Check parent domains (subdomain matching)
        parts = hostname.split('.')
        for i in range(len(parts)):
            domain = '.'.join(parts[i:])
            if domain in self.blocked_domains:
                return True

        return False

    def handle_connection(self, client_socket, client_address):
        """Handle a single client connection"""
        try:
            client_socket.settimeout(5.0)

            # Read the HTTP request (read up to 8KB or until we have the first line)
            buffer = client_socket.recv(8192)
            if not buffer:
                client_socket.close()
                return

            # Split to get first line
            lines = buffer.split(b'\r\n')
            request_line = lines[0].decode('utf-8', errors='ignore').strip()

            # Parse the request
            parts = request_line.split(' ')
            if len(parts) < 2:
                client_socket.close()
                return

            method = parts[0]
            url = parts[1]

            # Extract hostname
            if method == 'CONNECT':
                # HTTPS proxy request: CONNECT example.com:443 HTTP/1.1
                hostname = url.split(':')[0]
                port = int(url.split(':')[1]) if ':' in url else 443
            else:
                # HTTP proxy request: GET http://example.com/path HTTP/1.1
                if url.startswith('http://'):
                    url_parts = url[7:].split('/', 1)
                    hostname = url_parts[0].split(':')[0]
                    port = int(url_parts[0].split(':')[1]) if ':' in url_parts[0] else 80
                else:
                    # Relative URL, need to find Host header in the buffer we already read
                    hostname = None
                    for line in lines[1:]:
                        line_str = line.decode('utf-8', errors='ignore').strip()
                        if line_str.lower().startswith('host:'):
                            hostname = line_str.split(':', 1)[1].strip()
                            break

                    if not hostname:
                        client_socket.close()
                        return
                    port = 80

            # Check if blocked
            if self.should_block_domain(hostname):
                logger.info(f"🚫 Blocking {method} to: {hostname}")

                # Record the blocked attempt
                self.record_blocked_attempt(hostname)

                # Send error response
                if method == 'CONNECT':
                    response = b'HTTP/1.1 403 Forbidden\r\n\r\n'
                else:
                    response = b'HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\n\r\n<html><body><h1>Blocked by AlwaysBlock</h1></body></html>'

                try:
                    client_socket.sendall(response)
                except:
                    pass

                client_socket.close()
                return

            # Allow the connection
            logger.debug(f"✅ Allowing {method} to: {hostname}:{port}")

            # Connect to the real server
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.settimeout(5.0)

            try:
                server_socket.connect((hostname, port))
            except Exception as e:
                logger.error(f"Failed to connect to {hostname}:{port}: {e}")

                if method == 'CONNECT':
                    response = b'HTTP/1.1 502 Bad Gateway\r\n\r\n'
                else:
                    response = b'HTTP/1.1 502 Bad Gateway\r\n\r\n'

                try:
                    client_socket.sendall(response)
                except:
                    pass

                client_socket.close()
                server_socket.close()
                return

            if method == 'CONNECT':
                # HTTPS: Send 200 OK then just forward bytes
                client_socket.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')

                # Remove timeouts
                client_socket.settimeout(None)
                server_socket.settimeout(None)

                # Forward data bidirectionally
                self.forward_data(client_socket, server_socket)
            else:
                # HTTP: Forward the request and handle response
                # Send the original request to the server
                server_socket.sendall(request_line.encode() + b'\r\n')

                # Forward remaining headers and body
                while True:
                    data = client_socket.recv(8192)
                    if not data:
                        break
                    server_socket.sendall(data)
                    if len(data) < 8192:
                        break

                # Forward response back
                while True:
                    data = server_socket.recv(8192)
                    if not data:
                        break
                    client_socket.sendall(data)

                client_socket.close()
                server_socket.close()

        except socket.timeout:
            logger.debug(f"Connection timeout from {client_address[0]}")
        except Exception as e:
            logger.error(f"Error handling connection: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass

    def forward_data(self, client_socket, server_socket):
        """Forward data bidirectionally between sockets"""
        try:
            sockets = [client_socket, server_socket]

            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 60.0)

                if exceptional:
                    break

                if not readable:
                    break

                for sock in readable:
                    try:
                        data = sock.recv(8192)
                        if not data:
                            return

                        if sock is client_socket:
                            server_socket.sendall(data)
                        else:
                            client_socket.sendall(data)

                    except Exception as e:
                        logger.debug(f"Error forwarding data: {e}")
                        return

        except Exception as e:
            logger.debug(f"Connection forwarding error: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass
            try:
                server_socket.close()
            except:
                pass

    def start(self):
        """Start the HTTP proxy server"""
        try:
            self.load_blocked_domains()
            self.load_stats()

            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('127.0.0.1', self.port))
            self.server_socket.listen(128)

            self.running = True
            logger.info(f"🚀 HTTP proxy started on 127.0.0.1:{self.port}")
            logger.info(f"📋 Blocking {len(self.blocked_domains)} domains")

            # Start background thread to check for file changes and save stats
            def reload_checker():
                save_counter = 0
                while self.running:
                    time.sleep(5)
                    self.check_and_reload()

                    # Save stats every 30 seconds (6 iterations of 5s)
                    save_counter += 1
                    if save_counter >= 6:
                        self.save_stats()
                        save_counter = 0

            checker_thread = threading.Thread(target=reload_checker, daemon=True)
            checker_thread.start()

            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    try:
                        client_socket, client_address = self.server_socket.accept()
                    except socket.timeout:
                        continue

                    thread = threading.Thread(
                        target=self.handle_connection,
                        args=(client_socket, client_address),
                        daemon=True
                    )
                    thread.start()

                except KeyboardInterrupt:
                    logger.info("Shutting down proxy...")
                    break
                except Exception as e:
                    logger.error(f"Error accepting connection: {e}")

        except Exception as e:
            logger.error(f"Failed to start proxy: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop the proxy server"""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        # Save stats one final time before stopping
        self.save_stats()
        logger.info("Proxy stopped")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    proxy = HTTPProxy()
    proxy.start()
