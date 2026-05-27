# DNS Troubleshooting

## Symptom

Pages intermittently fail to load, especially burst-heavy ad, analytics, and CDN domains. A proxy extension like ZeroOmega reports "resources failed to load." Retrying often works. The cause is usually DNS, not AlwaysBlock's blocking.

## Why this happens through the proxy

When traffic goes through the proxy, your browser stops resolving hostnames itself and hands them to AlwaysBlock, which resolves them using your system DNS resolver. Browsers normally use their own DNS-over-HTTPS, which sidesteps a flaky resolver, but that protection is out of the loop once traffic is proxied. So if your resolver (often your router) is slow or unreliable under load, you see intermittent failures only through the proxy.

## Confirm it's DNS

```bash
grep -i "nodename nor servname\|Failed to connect" /tmp/proxy.log
```

`[Errno 8] nodename nor servname` is a DNS resolution failure, not a connection failure.

Check which resolver is in use:

```bash
scutil --dns | grep nameserver
```

### Important: rule out file descriptor exhaustion first

DNS failures and "Too many open files" failures often appear together at the same timestamps, because once the proxy runs out of file descriptors, `getaddrinfo` can no longer allocate a query socket and surfaces as the same `EAI_NONAME` error. Check for both:

```bash
grep -iE "error|fail|too many" /tmp/proxy.log | tail -40
```

If you see `[Errno 24] Too many open files` interleaved with the DNS errors, the underlying problem is FD exhaustion, not DNS. macOS launchd starts daemons with a soft `RLIMIT_NOFILE` of 256, which a busy page (many subdomains opening parallel connections) can blow past. The proxy now raises its own soft limit to 65536 at startup, so this should not recur after restart. To verify the live limit:

```bash
grep RLIMIT_NOFILE /tmp/proxy.log | tail -1
```

## Fix

Point your Mac at a reliable public resolver (1.1.1.1 is Cloudflare, 8.8.8.8 is Google):

```bash
sudo networksetup -setdnsservers Wi-Fi 1.1.1.1 1.0.0.1 8.8.8.8 8.8.4.4
```

To undo and hand DNS back to the router:

```bash
sudo networksetup -setdnsservers Wi-Fi Empty
```

## Built-in resilience

The proxy retries DNS and tries every resolved IP before giving up, so a single transient blip won't cause a hard failure. It also requires several clustered failures before pausing blocking for a suspected network outage, so one bad lookup can't silently disable blocking. A consistently flaky resolver still needs the fix above.
