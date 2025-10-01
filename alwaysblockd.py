#!/usr/bin/env python3
"""
alwaysblock - Clean, modern DNS-based domain blocker for macOS
Main daemon entry point
"""

import asyncio
import argparse
import signal
import sys
import logging
from typing import Dict, Set, Optional
from pathlib import Path

from dns_proxy import DNSProxy
from config_manager import ConfigManager
from pf_manager import PFManager
from cli_interface import CLIServer
from db import Database

logger = logging.getLogger(__name__)


class AlwaysBlockDaemon:
    """Main daemon orchestrating DNS proxy, PF management, and configuration"""
    
    def __init__(self, config_path: Path, dns_port: int = 5353):
        self.config_path = config_path
        self.dns_port = dns_port
        self.db = Database()
        self.config_manager = ConfigManager(config_path, db=self.db)
        self.pf_manager = PFManager()
        self.dns_proxy = DNSProxy(
            port=dns_port,
            config_manager=self.config_manager,
            pf_manager=self.pf_manager
        )
        self.cli_server = CLIServer(
            config_manager=self.config_manager,
            dns_proxy=self.dns_proxy,
            pf_manager=self.pf_manager,
            db=self.db
        )
        self.running = False
        self._session_check_task = None
        
    async def start(self):
        """Start all daemon components"""
        logger.info(f"Starting alwaysblock daemon on DNS port {self.dns_port}")
        self.running = True
        
        # Load initial configuration
        self.config_manager.load()
        
        # Start components
        await asyncio.gather(
            self.dns_proxy.start(),
            self.cli_server.start(),
            self._handle_signals(),
            self._session_checker()
        )
        
    async def stop(self):
        """Gracefully stop all components"""
        logger.info("Stopping alwaysblock daemon")
        self.running = False
        await self.dns_proxy.stop()
        await self.cli_server.stop()
        
    async def _handle_signals(self):
        """Handle system signals for graceful shutdown"""
        loop = asyncio.get_event_loop()
        
        def signal_handler(sig):
            logger.info(f"Received signal {sig}, shutting down")
            asyncio.create_task(self.stop())
            
        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
            
        # Keep running until stopped
        while self.running:
            await asyncio.sleep(1)
    
    async def _session_checker(self):
        """Periodically check and update session states"""
        while self.running:
            try:
                # Activate pending sessions
                activated = self.db.activate_pending_sessions()
                for session in activated:
                    logger.info(f"Activating session for domains: {', '.join(session['domains'])}")
                
                # Expire completed sessions
                expired = self.db.expire_sessions()
                for session in expired:
                    logger.info(f"Expiring session for domains: {', '.join(session['domains'])}")
                    # Flush DNS cache for expired domains
                    self.dns_proxy.flush_domain_cache(session['domains'])
                
            except Exception as e:
                logger.error(f"Error in session checker: {e}")
            
            # Check every 5 seconds
            await asyncio.sleep(5)


def setup_logging(verbose: bool = False):
    """Configure logging"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='alwaysblock DNS daemon')
    parser.add_argument(
        '--config', '-c',
        type=Path,
        default=Path.home() / '.config' / 'alwaysblock' / 'config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=5353,
        help='DNS proxy port (default: 5353)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # Create and run daemon
    daemon = AlwaysBlockDaemon(args.config, args.port)
    
    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()