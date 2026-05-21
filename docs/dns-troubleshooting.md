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
