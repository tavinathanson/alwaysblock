#!/usr/bin/env python3
"""
System proxy configuration for macOS
Sets system-wide HTTP/HTTPS proxy to our transparent proxy
"""
import subprocess
import logging

logger = logging.getLogger(__name__)


class SystemProxy:
    """Manages macOS system proxy settings"""

    def __init__(self, proxy_host="127.0.0.1", proxy_port=8905):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port

    def get_network_services(self):
        """Get list of network services"""
        try:
            result = subprocess.run(
                ['networksetup', '-listallnetworkservices'],
                capture_output=True,
                text=True,
                check=True
            )
            # First line is a header, skip it
            services = [s for s in result.stdout.strip().split('\n')[1:] if s and not s.startswith('*')]
            return services
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get network services: {e}")
            return []

    def enable_proxy(self):
        """Enable system proxy for all network services"""
        services = self.get_network_services()

        for service in services:
            try:
                # Set HTTP proxy
                subprocess.run(
                    ['networksetup', '-setwebproxy', service, self.proxy_host, str(self.proxy_port)],
                    check=True,
                    capture_output=True
                )

                # Set HTTPS proxy
                subprocess.run(
                    ['networksetup', '-setsecurewebproxy', service, self.proxy_host, str(self.proxy_port)],
                    check=True,
                    capture_output=True
                )

                logger.info(f"Enabled proxy for: {service}")

            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to set proxy for {service}: {e}")

        print(f"✅ System proxy enabled: {self.proxy_host}:{self.proxy_port}")
        print(f"   Applied to {len(services)} network service(s)")

    def disable_proxy(self):
        """Disable system proxy for all network services"""
        services = self.get_network_services()

        for service in services:
            try:
                # Disable HTTP proxy
                subprocess.run(
                    ['networksetup', '-setwebproxystate', service, 'off'],
                    check=True,
                    capture_output=True
                )

                # Disable HTTPS proxy
                subprocess.run(
                    ['networksetup', '-setsecurewebproxystate', service, 'off'],
                    check=True,
                    capture_output=True
                )

                logger.info(f"Disabled proxy for: {service}")

            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to disable proxy for {service}: {e}")

        print(f"✅ System proxy disabled")
        print(f"   Removed from {len(services)} network service(s)")

    def get_status(self):
        """Check if system proxy is enabled"""
        services = self.get_network_services()
        enabled_count = 0

        for service in services:
            try:
                # Check HTTP proxy
                result = subprocess.run(
                    ['networksetup', '-getwebproxy', service],
                    capture_output=True,
                    text=True,
                    check=True
                )

                # Check if proxy is configured AND enabled (not just configured)
                has_proxy = f"Server: {self.proxy_host}" in result.stdout and f"Port: {self.proxy_port}" in result.stdout
                is_enabled = "Enabled: Yes" in result.stdout

                if has_proxy and is_enabled:
                    enabled_count += 1

            except subprocess.CalledProcessError:
                pass

        return {
            'enabled': enabled_count > 0,
            'services_count': len(services),
            'enabled_count': enabled_count
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    proxy = SystemProxy()

    print("System Proxy Manager")
    print("=" * 50)
    print("\nNetwork Services:")
    for service in proxy.get_network_services():
        print(f"  - {service}")

    print("\nStatus:")
    status = proxy.get_status()
    print(f"Proxy enabled: {status['enabled']}")
    print(f"Services: {status['enabled_count']}/{status['services_count']}")
