"""
CLI interface for alwaysblock
Provides a simple socket-based control interface
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class CLIServer:
    """Socket server for CLI commands"""
    
    def __init__(self, config_manager, dns_proxy, pf_manager, db):
        self.config_manager = config_manager
        self.dns_proxy = dns_proxy
        self.pf_manager = pf_manager
        self.db = db
        # Use /tmp for socket - accessible by all users
        self.socket_path = Path('/tmp/alwaysblock.sock')
        self.server = None
        
    async def start(self):
        """Start CLI control server"""
        # Ensure socket directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove old socket if exists
        if self.socket_path.exists():
            self.socket_path.unlink()
        
        # Create Unix domain socket server
        self.server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(self.socket_path)
        )
        
        # Set socket permissions to allow all users
        os.chmod(self.socket_path, 0o666)
        
        logger.info(f"CLI control server listening on {self.socket_path}")
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self):
        """Stop CLI control server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # Clean up socket
        if self.socket_path.exists():
            self.socket_path.unlink()
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle CLI client connection"""
        try:
            # Read command (JSON)
            data = await reader.read(8192)
            if not data:
                return
                
            command = json.loads(data.decode())
            logger.debug(f"Received command: {command}")
            
            # Process command
            response = await self.process_command(command)
            
            # Send response
            writer.write(json.dumps(response).encode())
            await writer.drain()
            
        except json.JSONDecodeError:
            response = {'error': 'Invalid command format'}
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            logger.error(f"Error handling client: {e}")
            response = {'error': str(e)}
            writer.write(json.dumps(response).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def process_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Process a CLI command"""
        cmd = command.get('command')
        args = command.get('args', {})
        
        if cmd == 'status':
            return self._get_status()
        
        elif cmd == 'unblock':
            profile_name = args.get('profile', self.config_manager.get_default_profile())
            targets = args.get('targets', [])
            
            if not self.config_manager.is_valid_profile(profile_name):
                return {'error': f'Invalid profile: {profile_name}'}
            
            # Check cooldown
            timing = self.config_manager.calculate_timing(profile_name, targets)
            if not self.db.check_cooldown(profile_name, timing['cooldown']):
                return {'error': f"Profile '{profile_name}' is on cooldown"}
            
            # Resolve targets to domains
            resolved = self.config_manager.resolve_domains(targets)
            if not resolved:
                return {'error': 'No valid domains to unblock'}
            
            # Create session
            session_id = self.db.create_session(
                profile=profile_name,
                domains=resolved,
                wait_minutes=timing['wait'],
                duration_minutes=timing['duration']
            )
            
            # Update cooldown
            self.db.update_cooldown(profile_name)
            
            return {
                'status': 'success',
                'session_id': session_id,
                'profile': profile_name,
                'domains': resolved,
                'wait_minutes': timing['wait'],
                'duration_minutes': timing['duration']
            }
        
        elif cmd == 'cancel':
            session_id = args.get('session_id')
            if not session_id:
                return {'error': 'No session ID specified'}
            
            if self.db.cancel_session(session_id):
                return {
                    'status': 'success',
                    'message': f'Cancelled session {session_id}'
                }
            else:
                return {'error': f'Session {session_id} not found or already completed'}
        
        elif cmd == 'block-all':
            # Cancel all active sessions
            active = self.db.get_active_sessions()
            for session in active:
                self.db.cancel_session(session['id'])
            
            # Flush all PF states
            self.dns_proxy.flush_domain_cache(None)
            
            return {
                'status': 'success',
                'message': f'Blocked all domains and cancelled {len(active)} active sessions'
            }
        
        else:
            return {'error': f'Unknown command: {cmd}'}
    
    def _get_status(self) -> Dict[str, Any]:
        """Get current status with session information"""
        active_sessions = self.db.get_active_sessions()
        pending_sessions = self.db.get_pending_sessions()
        all_configured = self.config_manager.get_all_configured_domains()
        
        # Collect all currently unblocked domains
        unblocked_domains = set()
        for session in active_sessions:
            unblocked_domains.update(session['domains'])
        
        return {
            'status': 'running',
            'configured_count': len(all_configured),
            'active_sessions': len(active_sessions),
            'pending_sessions': len(pending_sessions),
            'unblocked_domains': sorted(list(unblocked_domains)),
            'sessions': [
                {
                    'id': s['id'],
                    'profile': s['profile'],
                    'domains': s['domains'],
                    'status': s['status'],
                    'remaining_minutes': max(0, int((s['end_at'] - datetime.now()).total_seconds() / 60))
                        if s['status'] == 'active' else s['wait_minutes']
                }
                for s in (active_sessions + pending_sessions)
            ]
        }