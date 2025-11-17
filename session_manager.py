#!/usr/bin/env python3
"""
Background daemon to process expired/pending sessions
Runs every 30 seconds to keep blocking state up to date
"""
import time
import sys
import json
from pathlib import Path
from alwaysblock import AlwaysBlock


def main():
    """Run session processing loop"""
    ab = AlwaysBlock()
    stats_file = Path('/tmp/alwaysblock_stats.json')

    while True:
        try:
            # Process expired and pending sessions
            ab._process_expired_sessions()

            # Update domains JSON for proxy
            ab._write_domains_for_proxy()

            # Sync stats from JSON to database
            try:
                if stats_file.exists():
                    with open(stats_file, 'r') as f:
                        data = json.load(f)
                        stats = data.get('stats', {})

                        if stats:
                            # Sync to database
                            ab.db.sync_stats_from_json(stats)

                            # Clear the JSON stats after syncing
                            with open(stats_file, 'w') as f_out:
                                json.dump({'stats': {}}, f_out)

            except Exception as e:
                print(f"Error syncing stats: {e}", file=sys.stderr)

        except Exception as e:
            print(f"Error processing sessions: {e}", file=sys.stderr)

        # Sleep for 30 seconds
        time.sleep(30)


if __name__ == '__main__':
    main()
