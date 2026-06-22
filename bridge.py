#!/usr/bin/env python3
"""
AlwaysBlock bridge — backend B's server side.

A tiny, READ-ONLY loopback HTTP server that exposes the brain's current state to
the Chrome extension:
  * GET /state    — the blocklist + active/pending/queued sessions
  * GET /resolve  — map a visited host to the CLI target that unblocks it

The extension is a dumb enforcer/viewer: it reflects state and blocks. It never
changes state — requesting access, disabling, etc. all happen through the
`alwaysblock` CLI, which is the single control surface. ALL blocking logic —
timing, queueing, cooldowns, the disable-until-midnight state — stays in the
Python brain (alwaysblock.py); the bridge only reads it.

Design notes:
  * Binds to 127.0.0.1 only, and is read-only, so a local process can learn the
    blocklist but cannot use it to disable blocking. (This tool is soft friction
    regardless — a hard lock comes from a managed-policy force-install, not this
    port.)
  * Pure standard library — no extra pip dependencies beyond what the brain
    already needs (PyYAML).
  * Each request constructs a fresh AlwaysBlock, exactly like a CLI invocation:
    the brain keeps all durable state in SQLite, so there's no shared in-memory
    state to make thread-safe.
  * GET /state runs expiry/queue processing first, so polling the bridge is what
    advances sessions for an extension-only machine — no separate expiry daemon
    is required for this backend.

Run it with:  alwaysblock bridge start   (background, manual)
              alwaysblock bridge run     (foreground, used by the LaunchAgent)
"""
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("alwaysblock.bridge")


class BridgeHandler(BaseHTTPRequestHandler):
    # Quieter logs; the brain prints its own messages.
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    # --- helpers -----------------------------------------------------------
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # The extension fetches with host_permissions, so CORS isn't strictly
        # required, but permissive loopback CORS keeps curl/testing and
        # extension-page fetches frictionless.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _brain(self):
        """The shared brain (built once in serve()), with config re-read so
        on-disk edits to config.yaml show up without restarting the bridge.
        Reusing one brain avoids re-initializing the SQLite schema on every poll;
        only the cheap config reload runs per request."""
        brain = self.server.brain
        brain.config_manager.load()
        return brain

    # --- routes (read-only) ------------------------------------------------
    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        parts = urlsplit(self.path)
        route = parts.path

        if route == "/state":
            try:
                brain = self._brain()
                # Advance sessions (expire finished, activate pending/queued) so a
                # poll keeps the extension's view current with no expiry daemon.
                brain._process_expired_sessions()
                # write_file=False: the bridge only needs the dict to serve; the
                # proxy's own writers own the state file.
                state = brain._write_state(write_file=False)
                self._send(200, state)
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to build state")
                self._send(500, {"error": str(e)})
            return

        if route == "/resolve":
            # Map a visited host to the config target the CLI understands, so the
            # block page can show an exact `alwaysblock unblock <target>` command.
            host = (parse_qs(parts.query).get("host", [""])[0] or "").strip()
            try:
                target = self._brain().config_manager.resolve_host_to_target(host)
                self._send(200, {"host": host, "target": target})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
            return

        self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8906):
    """Run the bridge in the foreground until interrupted."""
    # Lazy import avoids a circular import (alwaysblock.py imports serve()).
    from alwaysblock import AlwaysBlock
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [bridge] %(message)s")
    server = ThreadingHTTPServer((host, port), BridgeHandler)
    # One long-lived brain shared across requests (each DB call opens its own
    # SQLite connection, so this is thread-safe under the threading server).
    server.brain = AlwaysBlock()
    logger.info("AlwaysBlock bridge listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
