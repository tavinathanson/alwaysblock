"""
DNS proxy for alwaysblock
Intercepts DNS requests and blocks configured domains
"""
import asyncio
import logging
import socket
from typing import Dict, Set, Optional, Tuple, List
from threading import RLock
import time

from dnslib import DNSRecord, DNSHeader, RR, QTYPE, A
from dnslib.server import DNSServer, BaseResolver

logger = logging.getLogger(__name__)


class BlockingResolver(BaseResolver):
    """DNS resolver that blocks configured domains"""
    
    def __init__(self, config_manager, pf_manager, upstream_dns='8.8.8.8'):
        self.config_manager = config_manager
        self.pf_manager = pf_manager
        self.upstream_dns = upstream_dns
        self.upstream_port = 53
        
        # Domain -> IP cache for unblocked domains
        self.domain_ip_cache: Dict[str, Set[str]] = {}
        self.cache_lock = RLock()
        
        # Cache TTL (5 minutes)
        self.cache_ttl = 300
        self.cache_timestamps: Dict[str, float] = {}
    
    def resolve(self, request, handler):
        """Resolve DNS request"""
        reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=1, ra=1))
        qname = request.q.qname
        qtype = request.q.qtype
        domain = str(qname).rstrip('.')
        
        # Only handle A records for now
        if qtype != QTYPE.A:
            # Forward non-A queries upstream
            return self._forward_upstream(request)
        
        # Check if domain is blocked
        if self.config_manager.is_domain_blocked(domain):
            # Return 0.0.0.0 for blocked domains
            logger.debug(f"Blocking domain: {domain}")
            reply.add_answer(RR(qname, QTYPE.A, rdata=A("0.0.0.0"), ttl=60))
            return reply
        
        # Domain is unblocked - forward to upstream DNS
        logger.debug(f"Allowing domain: {domain}")
        upstream_reply = self._forward_upstream(request)
        
        # Cache the IPs for this domain
        if upstream_reply:
            self._cache_domain_ips(domain, upstream_reply)
            
        return upstream_reply
    
    def _forward_upstream(self, request):
        """Forward request to upstream DNS server"""
        try:
            # Send request to upstream DNS
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(request.pack(), (self.upstream_dns, self.upstream_port))
            response, _ = sock.recvfrom(8192)
            sock.close()
            
            return DNSRecord.parse(response)
        except Exception as e:
            logger.error(f"Failed to forward DNS request: {e}")
            # Return empty response on error
            return DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=1, ra=1))
    
    def _cache_domain_ips(self, domain: str, reply: DNSRecord):
        """Extract and cache IPs from DNS reply"""
        ips = set()
        for rr in reply.rr:
            if rr.rtype == QTYPE.A:
                ips.add(str(rr.rdata))
        
        if ips:
            with self.cache_lock:
                self.domain_ip_cache[domain] = ips
                self.cache_timestamps[domain] = time.time()
                logger.debug(f"Cached IPs for {domain}: {ips}")
    
    def get_cached_ips(self, domain: str) -> Set[str]:
        """Get cached IPs for a domain"""
        with self.cache_lock:
            # Check if cache is expired
            if domain in self.cache_timestamps:
                if time.time() - self.cache_timestamps[domain] > self.cache_ttl:
                    # Expired - remove from cache
                    self.domain_ip_cache.pop(domain, None)
                    self.cache_timestamps.pop(domain, None)
                    return set()
            
            return self.domain_ip_cache.get(domain, set()).copy()
    
    def get_all_cached_ips(self) -> Dict[str, Set[str]]:
        """Get all cached domain->IP mappings"""
        with self.cache_lock:
            # Clean expired entries
            now = time.time()
            expired = [
                domain for domain, ts in self.cache_timestamps.items()
                if now - ts > self.cache_ttl
            ]
            for domain in expired:
                self.domain_ip_cache.pop(domain, None)
                self.cache_timestamps.pop(domain, None)
            
            return self.domain_ip_cache.copy()
    
    def clear_cache(self):
        """Clear the DNS cache"""
        with self.cache_lock:
            self.domain_ip_cache.clear()
            self.cache_timestamps.clear()


class DNSProxy:
    """Async DNS proxy server"""
    
    def __init__(self, port: int, config_manager, pf_manager):
        self.port = port
        self.config_manager = config_manager
        self.pf_manager = pf_manager
        self.resolver = BlockingResolver(config_manager, pf_manager)
        self.server = None
        self._running = False
    
    async def start(self):
        """Start DNS proxy server"""
        logger.info(f"Starting DNS proxy on port {self.port}")
        
        # Create DNS server (runs in thread)
        self.server = DNSServer(
            self.resolver,
            port=self.port,
            address='127.0.0.1'
        )
        
        # Start in background thread
        self._running = True
        await asyncio.get_event_loop().run_in_executor(
            None, self._run_server
        )
    
    def _run_server(self):
        """Run DNS server (blocking)"""
        try:
            self.server.start_thread()
            # Keep thread alive
            while self._running:
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"DNS server error: {e}")
        finally:
            if self.server:
                self.server.stop()
    
    async def stop(self):
        """Stop DNS proxy server"""
        logger.info("Stopping DNS proxy")
        self._running = False
        if self.server:
            self.server.stop()
    
    def flush_domain_cache(self, domains: Optional[List[str]] = None):
        """
        Flush DNS cache and PF states for domains
        If domains is None, flush everything
        """
        if domains is None:
            # Flush all
            all_ips = set()
            for ips in self.resolver.get_all_cached_ips().values():
                all_ips.update(ips)
            
            if all_ips:
                logger.info(f"Flushing PF states for {len(all_ips)} IPs")
                self.pf_manager.flush_states(list(all_ips))
            
            self.resolver.clear_cache()
        else:
            # Flush specific domains
            all_ips = set()
            for domain in domains:
                ips = self.resolver.get_cached_ips(domain)
                all_ips.update(ips)
            
            if all_ips:
                logger.info(f"Flushing PF states for {len(all_ips)} IPs from {len(domains)} domains")
                self.pf_manager.flush_states(list(all_ips))