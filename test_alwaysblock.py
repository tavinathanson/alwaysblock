#!/usr/bin/env python3
"""
Simple test script for alwaysblock
Tests DNS resolution and blocking functionality
"""
import socket
import subprocess
import time
import sys


def test_dns_resolution(domain, expected_blocked=True):
    """Test if domain resolves correctly"""
    try:
        # Use system DNS (which should be pointing to alwaysblock)
        result = socket.gethostbyname(domain)
        
        if expected_blocked and result == "0.0.0.0":
            print(f"✓ {domain} correctly blocked (resolved to 0.0.0.0)")
            return True
        elif not expected_blocked and result != "0.0.0.0":
            print(f"✓ {domain} correctly unblocked (resolved to {result})")
            return True
        else:
            print(f"✗ {domain} incorrectly {'unblocked' if expected_blocked else 'blocked'} (resolved to {result})")
            return False
    except Exception as e:
        print(f"✗ Failed to resolve {domain}: {e}")
        return False


def run_cli_command(args):
    """Run alwaysblock CLI command"""
    try:
        result = subprocess.run(
            ['./alwaysblock'] + args,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(args)}")
        print(f"Error: {e.stderr}")
        return None


def main():
    """Run tests"""
    print("alwaysblock Test Suite")
    print("=" * 50)
    print()
    
    # Check if daemon is running
    print("1. Checking daemon status...")
    status = run_cli_command(['status'])
    if status is None:
        print("✗ Daemon not running. Start it with: python3 alwaysblockd.py")
        sys.exit(1)
    print("✓ Daemon is running")
    print()
    
    # Test domains to check
    test_domains = ['google.com', 'netflix.com', 'github.com']
    
    # Test 1: Block all
    print("2. Testing block-all...")
    run_cli_command(['block-all'])
    time.sleep(1)  # Give DNS cache time to update
    
    all_blocked = True
    for domain in test_domains:
        if not test_dns_resolution(domain, expected_blocked=True):
            all_blocked = False
    
    if all_blocked:
        print("✓ All domains correctly blocked")
    print()
    
    # Test 2: Unblock specific domain
    print("3. Testing unblock specific domain...")
    run_cli_command(['unblock', 'google.com'])
    time.sleep(1)
    
    test_dns_resolution('google.com', expected_blocked=False)
    test_dns_resolution('netflix.com', expected_blocked=True)
    print()
    
    # Test 3: Unblock multiple domains
    print("4. Testing unblock multiple domains...")
    run_cli_command(['unblock', 'netflix.com', 'github.com'])
    time.sleep(1)
    
    test_dns_resolution('netflix.com', expected_blocked=False)
    test_dns_resolution('github.com', expected_blocked=False)
    print()
    
    # Test 4: Block specific domain
    print("5. Testing block specific domain...")
    run_cli_command(['block', 'netflix.com'])
    time.sleep(1)
    
    test_dns_resolution('netflix.com', expected_blocked=True)
    test_dns_resolution('google.com', expected_blocked=False)  # Should still be unblocked
    print()
    
    # Test 5: Status check
    print("6. Testing status command...")
    status_output = run_cli_command(['status'])
    if status_output:
        print(status_output)
        print("✓ Status command working")
    print()
    
    # Cleanup: block all again
    print("7. Cleanup - blocking all domains...")
    run_cli_command(['block-all'])
    print("✓ Test suite complete")


if __name__ == '__main__':
    main()