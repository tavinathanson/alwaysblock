#!/usr/bin/env python3
"""
AlwaysBlock menubar (a SwiftBar plugin; the ".2s" in the filename is its refresh rate).

Icon is a lock when everything is blocked, a numbered circle for 1 to 3 open
unblock sessions, an ellipsis circle for more, and a pause circle while paused.
It turns orange while a session is pending or queued (an hourglass if none is
open yet). Clicking it shows the regular `alwaysblock status` text plus a
"Cancel" item per open, pending, or queued session. No logic of its own: it runs
the CLI (which refreshes the shared state file) and reads that file, the same
blob the proxy and bridge use.

Setup:  brew install --cask swiftbar, then point SwiftBar's plugin folder at this
directory (or symlink this file into the folder you already use).
"""
import json
import os
import subprocess
import time

CLI = "/usr/local/bin/alwaysblock"
STATE_FILE = os.environ.get("ALWAYSBLOCK_STATE_FILE", "/tmp/alwaysblock_domains.json")


def action(label, *args):
    params = " ".join(f"param{i}={a}" for i, a in enumerate(args, 1))
    return f"{label} | bash={CLI} {params} terminal=false refresh=true"


def until(epoch):
    """Compact time until epoch; seconds under 3 minutes, like format_time_remaining in the CLI."""
    secs = max(0, int(epoch - time.time()))
    return f"{secs}s" if secs < 180 else f"{secs // 60}m"


status = subprocess.run([CLI, "status"], capture_output=True, text=True).stdout
with open(STATE_FILE) as f:
    state = json.load(f)

active = state.get("active_sessions", [])
pending = state.get("pending_sessions", [])
waiting = state.get("waiting_sessions", [])
paused = state.get("pause_until", 0) > time.time()
n = len(active)
icon = ("pause.circle.fill" if paused else f"{n}.circle.fill" if 0 < n <= 3
        else "ellipsis.circle.fill" if n else "hourglass" if pending or waiting else "lock.fill")
# Orange while anything is still waiting to open, on top of whatever is open now.
color = " sfcolor=#FF9500" if pending or waiting else ""
print(f" | sfimage={icon}{color}")
print("---")

actions = (
    [action(f"Cancel {s['name']} ({until(s['end_at'])} left)", "cancel", s["id"]) for s in active]
    + [action(f"Cancel {s['name']} (opens in {until(s['start_at'])})", "cancel", s["id"])
       for s in pending]
    + [action(f"Cancel {s['name']} (queued)", "cancel", s["id"]) for s in waiting]
    + ([action("Resume blocking", "resume")] if paused else [])
)
if actions:
    print("\n".join(actions + ["---"]))

for line in status.splitlines():
    print(f"{line.replace('|', '¦') or ' '} | font=Menlo size=11 trim=false")
print("---")
print("Refresh | refresh=true")
