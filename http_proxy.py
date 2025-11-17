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
from pathlib import Path

logger = logging.getLogger(__name__)


class HTTPProxy:
    """HTTP/HTTPS proxy that blocks based on hostname"""

    def __init__(self, port=8905, blocked_domains_file="/tmp/alwaysblock_domains.json"):
        self.port = port
        self.blocked_domains_file = Path(blocked_domains_file)
        self.blocked_domains = set()
        self.excluded_domains = set()
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
                    self.excluded_domains = set(data.get('excluded', []))
                    self.last_mtime = self.blocked_domains_file.stat().st_mtime
                    logger.info(f"Loaded {len(self.blocked_domains)} blocked domains, {len(self.excluded_domains)} excluded")
            else:
                logger.warning(f"Blocked domains file not found: {self.blocked_domains_file}")
                self.blocked_domains = set()
                self.excluded_domains = set()
        except Exception as e:
            logger.error(f"Failed to load blocked domains: {e}")
            self.blocked_domains = set()
            self.excluded_domains = set()

    def check_and_reload(self):
        """Check if domains file changed and reload if needed"""
        try:
            if self.blocked_domains_file.exists():
                mtime = self.blocked_domains_file.stat().st_mtime
                if mtime > self.last_mtime:
                    self.load_blocked_domains()
        except Exception as e:
            logger.debug(f"Error checking file mtime: {e}")

    def should_block_domain(self, hostname):
        """Check if domain should be blocked (with subdomain matching)"""
        if not hostname:
            return False

        # First check if domain is explicitly excluded (takes precedence)
        if hostname in self.excluded_domains:
            return False

        # Check without www prefix for exclusions
        if hostname.startswith('www.'):
            if hostname[4:] in self.excluded_domains:
                return False

        # Check if any parent domain is excluded
        parts = hostname.split('.')
        for i in range(len(parts)):
            domain = '.'.join(parts[i:])
            if domain in self.excluded_domains:
                return False

        # Now check if domain should be blocked
        # Direct match
        if hostname in self.blocked_domains:
            return True

        # Check without www prefix
        if hostname.startswith('www.'):
            if hostname[4:] in self.blocked_domains:
                return True

        # Check parent domains (subdomain matching)
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

            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('127.0.0.1', self.port))
            self.server_socket.listen(128)

            self.running = True
            logger.info(f"🚀 HTTP proxy started on 127.0.0.1:{self.port}")
            logger.info(f"📋 Blocking {len(self.blocked_domains)} domains")

            # Start background thread to check for file changes
            def reload_checker():
                while self.running:
                    time.sleep(5)
                    self.check_and_reload()

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
        logger.info("Proxy stopped")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    proxy = HTTPProxy()
    proxy.start()
