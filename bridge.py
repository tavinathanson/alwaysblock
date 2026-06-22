#!/usr/bin/env python3
"""
AlwaysBlock bridge — backend B's server side.

A tiny loopback HTTP server that exposes the same brain the CLI uses to the
Chrome extension. The extension is a dumb enforcer: it polls GET /state for the
current blocklist and POSTs commands (unblock/disable/resume/block-all) back.
ALL blocking logic — timing, queueing, cooldowns, the disable-until-midnight
state — stays in the Python brain (alwaysblock.py). Nothing here re-implements
it, which is what keeps the proxy and the extension perfectly consistent.

Design notes:
  * Binds to 127.0.0.1 only. It is reachable by any local process, not just the
    extension. That's an accepted tradeoff: this tool is *soft* friction (you
    can already defeat it by opening Safari or another browser), so a loopback
    control port is not a meaningful new hole. If you ever want it to be a hard
    lock, that comes from a managed-policy force-install + disabling Incognito,
    not from locking down this port.
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


def _new_brain():
    """Construct a fresh brain instance (imported lazily to avoid a circular
    import: alwaysblock.py imports serve() from here for `bridge run`)."""
    from alwaysblock import AlwaysBlock
    return AlwaysBlock()


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _run_command(self, fn):
        """Run a brain command that prints to stdout and may sys.exit() on a
        validation error. Capture both so a bad request returns a clean JSON
        error instead of killing the worker thread."""
        import io
        import contextlib
        buf = io.StringIO()
        ok = True
        try:
            with contextlib.redirect_stdout(buf):
                fn()
        except SystemExit:
            # The brain calls sys.exit(1) for invalid profile/target etc.
            ok = False
        except Exception as e:  # noqa: BLE001 - surface any brain error to client
            ok = False
            buf.write(f"\nerror: {e}")
        return ok, buf.getvalue().strip()

    # --- routes ------------------------------------------------------------
    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        parts = urlsplit(self.path)
        route = parts.path

        if route == "/state":
            try:
                brain = _new_brain()
                # Advance sessions (expire finished, activate pending/queued) so a
                # poll keeps the extension's view current with no expiry daemon.
                brain._process_expired_sessions()
                state = brain._write_state()
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
                target = _new_brain().config_manager.resolve_host_to_target(host)
                self._send(200, {"host": host, "target": target})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        body = self._read_json_body()
        try:
            brain = _new_brain()
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

        if route == "/unblock":
            host = (body.get("domain") or "").strip()
            profile = body.get("profile") or None
            if not host:
                return self._send(400, {"ok": False, "error": "missing 'domain'"})
            # The extension sends the host the user navigated to; map it to the
            # config target (domain or group) the brain knows how to unblock.
            target = brain.config_manager.resolve_host_to_target(host) or host
            ok, output = self._run_command(lambda: brain.unblock([target], profile))
            return self._send(200 if ok else 400,
                              {"ok": ok, "output": output, "target": target})

        if route == "/disable":
            ok, output = self._run_command(brain.disable)
            return self._send(200, {"ok": ok, "output": output})

        if route == "/resume":
            ok, output = self._run_command(brain.resume)
            return self._send(200, {"ok": ok, "output": output})

        if route == "/block-all":
            ok, output = self._run_command(brain.block_all)
            return self._send(200, {"ok": ok, "output": output})

        return self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8906):
    """Run the bridge in the foreground until interrupted."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [bridge] %(message)s")
    server = ThreadingHTTPServer((host, port), BridgeHandler)
    logger.info("AlwaysBlock bridge listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
