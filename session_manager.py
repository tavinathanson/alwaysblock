#!/usr/bin/env python3
"""
Background daemon to process expired/pending sessions
Runs every 30 seconds to keep blocking state up to date
"""
import time
import sys
from pathlib import Path
from alwaysblock import AlwaysBlock


def main():
    """Run session processing loop"""
    ab = AlwaysBlock()

    while True:
        try:
            # Process expired and pending sessions
            ab._process_expired_sessions()

            # Update domains JSON for proxy
            ab._write_domains_for_proxy()

        except Exception as e:
            print(f"Error processing sessions: {e}", file=sys.stderr)

        # Sleep for 30 seconds
        time.sleep(30)


if __name__ == '__main__':
    main()
