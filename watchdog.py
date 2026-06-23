#!/usr/bin/env python3
"""
AlwaysBlock app watchdog — an OPT-IN helper that quits native apps while their
sites are blocked.

The proxy backend already blocks a native app's traffic, but apps like Slack
hide the failure: a message looks sent, then silently doesn't go through. This
watchdog removes that ambiguity by quitting the app whenever its sites are
blocked, so "blocked" is unmistakable. When you `unblock slack`, it stops
quitting and you can reopen the app normally.

This is OFF by default. It does nothing unless you add a `kill_apps:` block to
your config.yaml (see README / example config). Like the Chrome bridge, it runs
as YOU (per-user LaunchAgent, no sudo, no system changes) — it only reads the
brain's state and sends SIGTERM to apps you listed.

Why a poll loop: the slow part of the old "AppleScript that kills Slack" wasn't
the kill, it was noticing late — Slack would run for several seconds first. We
poll the brain ~1s and SIGTERM immediately, so an app you open while blocked is
closed almost as fast as it opens.

Run it with:  alwaysblock watchdog start   (background, manual)
              alwaysblock watchdog run     (foreground, used by the LaunchAgent)
"""
import logging
import subprocess
import time

logger = logging.getLogger("alwaysblock.watchdog")

# How often to re-check the blocked state and running apps. A tiny JSON/SQLite
# read plus a `pgrep` per app is cheap, so a tight interval keeps the "app ran
# for a few seconds before it got killed" window small.
POLL_SECONDS = 1.0


def _app_is_running(app: str) -> bool:
    """True if a process whose name exactly matches `app` is running."""
    try:
        return subprocess.run(
            ["pgrep", "-x", app],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:  # noqa: BLE001 — never let a probe crash the loop
        return False


def _quit_app(app: str) -> None:
    """SIGTERM every process whose name exactly matches `app`.

    SIGTERM (not SIGKILL) lets Electron apps shut down cleanly without the slow
    "are you sure you want to quit?" AppleScript dialog. If the app relaunches
    (e.g. a login item) while still blocked, the next poll quits it again.
    """
    try:
        subprocess.run(
            ["pkill", "-x", app],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to quit %s", app)


def _should_be_blocked(brain, domains) -> bool:
    """Mirror the proxy's verdict: are any of `domains` blocked right now?

    Honors an active pause / disable-until-midnight (during which nothing
    blocks, so we must not quit anything) and active unblock sessions.
    """
    if brain._get_pause_until() > time.time():
        return False
    return any(brain.config_manager.is_domain_blocked(d) for d in domains)


def serve(poll_seconds: float = POLL_SECONDS):
    """Run the watchdog loop in the foreground until interrupted."""
    # Lazy import avoids a circular import (alwaysblock.py imports serve()).
    from alwaysblock import AlwaysBlock
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [watchdog] %(message)s")

    brain = AlwaysBlock()
    logger.info("AlwaysBlock app watchdog started (poll every %ss)", poll_seconds)

    last_mtime = None
    while True:
        try:
            # Reload config only when it actually changes, so edits to kill_apps
            # take effect without a restart but we don't re-parse (and log) every
            # tick. Advance sessions so an expired unblock is noticed promptly
            # even if no proxy/bridge daemon is running.
            try:
                mtime = brain.config_path.stat().st_mtime
            except OSError:
                mtime = None
            if mtime != last_mtime:
                brain.config_manager.load()
                last_mtime = mtime
            brain._process_expired_sessions()

            apps = brain.config_manager.get_kill_apps()
            for entry in apps:
                if _should_be_blocked(brain, entry["domains"]) and _app_is_running(entry["app"]):
                    logger.info("%s is blocked — quitting it", entry["app"])
                    _quit_app(entry["app"])
        except Exception:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.exception("Watchdog tick failed")

        time.sleep(poll_seconds)


if __name__ == "__main__":
    try:
        serve()
    except KeyboardInterrupt:
        pass
