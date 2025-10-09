#!/usr/bin/env python3
"""
AlwaysBlock CLI - Network Extension version
Manages blocked domains by writing to a JSON file that the Network Extension monitors
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import subprocess


class AlwaysBlockCLI:
    """CLI for managing AlwaysBlock Network Extension"""
    
    def __init__(self):
        # Use the same path as the Network Extension
        self.domains_file = Path.home() / "Documents" / "alwaysblock_domains.json"
        self.load_domains()
    
    def load_domains(self):
        """Load blocked domains from file"""
        if self.domains_file.exists():
            try:
                with open(self.domains_file, 'r') as f:
                    data = json.load(f)
                    self.domains = set(data.get('domains', []))
                    # Convert timestamps back to datetime objects
                    self.expirations = {
                        domain: datetime.fromtimestamp(ts)
                        for domain, ts in data.get('expirations', {}).items()
                    }
            except Exception as e:
                print(f"Error loading domains: {e}", file=sys.stderr)
                self.domains = set()
                self.expirations = {}
        else:
            self.domains = set()
            self.expirations = {}
    
    def save_domains(self):
        """Save blocked domains to file"""
        # Clean expired domains first
        self.clean_expired()
        
        data = {
            'domains': list(self.domains),
            'expirations': {
                domain: ts.timestamp()
                for domain, ts in self.expirations.items()
            }
        }
        
        # Ensure directory exists
        self.domains_file.parent.mkdir(exist_ok=True)
        
        with open(self.domains_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def clean_expired(self):
        """Remove expired domains"""
        now = datetime.now()
        expired = [
            domain for domain, expiry in self.expirations.items()
            if expiry < now
        ]
        for domain in expired:
            self.domains.discard(domain)
            del self.expirations[domain]
    
    def clean_domain(self, domain):
        """Clean and normalize domain"""
        # Remove protocol
        if '://' in domain:
            domain = domain.split('://')[1]
        
        # Remove path
        domain = domain.split('/')[0]
        
        # Remove port
        domain = domain.split(':')[0]
        
        # Remove www prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return domain.lower()
    
    def block(self, domain, duration=0):
        """Block a domain"""
        domain = self.clean_domain(domain)
        
        self.domains.add(domain)
        
        if duration > 0:
            expiry = datetime.now() + timedelta(minutes=duration)
            self.expirations[domain] = expiry
            print(f"Blocked {domain} until {expiry.strftime('%Y-%m-%d %H:%M')}")
        else:
            # Remove any existing expiration
            self.expirations.pop(domain, None)
            print(f"Blocked {domain} permanently")
        
        self.save_domains()
    
    def unblock(self, domain):
        """Unblock a domain"""
        domain = self.clean_domain(domain)
        
        if domain in self.domains:
            self.domains.remove(domain)
            self.expirations.pop(domain, None)
            print(f"Unblocked {domain}")
            self.save_domains()
        else:
            print(f"{domain} is not blocked")
    
    def unblock_all(self):
        """Unblock all domains"""
        count = len(self.domains)
        self.domains.clear()
        self.expirations.clear()
        self.save_domains()
        print(f"Unblocked all {count} domains")
    
    def status(self):
        """Show blocked domains"""
        self.clean_expired()
        
        if not self.domains:
            print("No domains are currently blocked")
            return
        
        print("Blocked domains:")
        for domain in sorted(self.domains):
            if domain in self.expirations:
                expiry = self.expirations[domain]
                remaining = expiry - datetime.now()
                if remaining.total_seconds() > 0:
                    mins = int(remaining.total_seconds() / 60)
                    print(f"  {domain} (expires in {mins} minutes)")
                else:
                    print(f"  {domain} (expired)")
            else:
                print(f"  {domain}")
    
    def check_extension_status(self):
        """Check if Network Extension is installed"""
        try:
            result = subprocess.run(
                ['systemextensionsctl', 'list'],
                capture_output=True,
                text=True
            )
            
            if 'com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension' in result.stdout:
                return True
            return False
        except:
            return False


def main():
    parser = argparse.ArgumentParser(
        description='AlwaysBlock - Network Extension based website blocker'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Status command
    subparsers.add_parser('status', help='Show blocked domains')
    
    # Block command
    block_parser = subparsers.add_parser('block', help='Block a domain')
    block_parser.add_argument('domain', help='Domain to block (e.g., reddit.com)')
    block_parser.add_argument(
        '-d', '--duration', type=int, default=0,
        help='Duration in minutes (0 for permanent)'
    )
    
    # Unblock command
    unblock_parser = subparsers.add_parser('unblock', help='Unblock a domain')
    unblock_parser.add_argument('domain', help='Domain to unblock')
    
    # Unblock all command
    subparsers.add_parser('unblock-all', help='Unblock all domains')
    
    args = parser.parse_args()
    
    # Default to status if no command
    if not args.command:
        args.command = 'status'
    
    cli = AlwaysBlockCLI()
    
    # Check if extension is installed
    if not cli.check_extension_status():
        print("Warning: AlwaysBlock Network Extension is not installed.", file=sys.stderr)
        print("Please run the AlwaysBlock app first to install the extension.", file=sys.stderr)
        print("", file=sys.stderr)
    
    if args.command == 'status':
        cli.status()
    elif args.command == 'block':
        cli.block(args.domain, args.duration)
    elif args.command == 'unblock':
        cli.unblock(args.domain)
    elif args.command == 'unblock-all':
        cli.unblock_all()


if __name__ == '__main__':
    main()