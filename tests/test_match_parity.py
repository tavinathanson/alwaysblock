#!/usr/bin/env python3
"""Parity test: the proxy backend and the Chrome (DNR) backend must make the
EXACT same block/allow decision for every host.

The proxy decides in Python via HTTPProxy.should_block_domain. The Chrome
extension decides via declarativeNetRequest `requestDomains` rules generated in
rules.js. `requestDomains: [h]` matches h and all its subdomains, with excluded
`allow` rules winning by priority. dnr_reference() below encodes exactly that
contract. If this test ever fails, the two backends have drifted and rules.js
(or the proxy) needs to be brought back in line.
"""
import pytest
from http_proxy import HTTPProxy


def dnr_reference(host, blocked, excluded):
    """Reference model of the Chrome backend's matching (see rules.js).

    A host is blocked iff it equals or is a subdomain of a blocked entry, and is
    NOT equal to / a subdomain of an excluded entry (excluded wins by priority).
    """
    def matches(h, entries):
        return any(h == d or h.endswith("." + d) for d in entries)

    if matches(host, excluded):
        return False
    return matches(host, blocked)


def proxy_decision(host, blocked, excluded):
    """The actual proxy code path, with runtime escapes (pause/captive) off."""
    p = HTTPProxy()
    p.blocked_domains = set(blocked)
    p.excluded_domains = set(excluded)
    p.pause_until = 0
    p.captive_portal_mode = False
    p.captive_portal_entered_at = 0
    return p.should_block_domain(host)


# (blocked_set, excluded_set, host) cases spanning the tricky combinations.
BLOCKED = {"reddit.com", "google.com", "twitter.com", "x.com", "youtube.com"}
EXCLUDED = {"accounts.google.com", "mail.google.com"}

HOSTS = [
    "reddit.com",            # exact blocked
    "www.reddit.com",        # www of blocked
    "old.reddit.com",        # subdomain of blocked
    "i.redd.it",             # unrelated host -> not configured
    "google.com",            # blocked parent
    "maps.google.com",       # blocked subdomain (not excluded)
    "accounts.google.com",   # excluded exact -> allowed despite google.com blocked
    "deep.accounts.google.com",  # subdomain of excluded -> allowed
    "mail.google.com",       # excluded exact
    "x.com",                 # blocked (group member style)
    "abs.twimg.com",         # not configured
    "example.com",           # not configured
    "youtube.com",           # blocked
    "m.youtube.com",         # blocked subdomain
]


@pytest.mark.parametrize("host", HOSTS)
def test_proxy_and_dnr_agree(host):
    proxy = proxy_decision(host, BLOCKED, EXCLUDED)
    dnr = dnr_reference(host, BLOCKED, EXCLUDED)
    assert proxy == dnr, (
        f"Backends disagree on {host!r}: proxy={proxy}, dnr={dnr}. "
        f"rules.js and http_proxy.py have drifted."
    )


def test_excluded_beats_blocked_parent():
    # Sanity: an excluded subdomain stays allowed even though its parent blocks.
    assert proxy_decision("accounts.google.com", BLOCKED, EXCLUDED) is False
    assert dnr_reference("accounts.google.com", BLOCKED, EXCLUDED) is False


def test_unconfigured_host_is_allowed_by_both():
    assert proxy_decision("example.com", BLOCKED, EXCLUDED) is False
    assert dnr_reference("example.com", BLOCKED, EXCLUDED) is False
