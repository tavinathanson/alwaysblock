"""
PF (Packet Filter) manager for macOS
Flushes connection states when domains are re-blocked
"""
import logging
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


class PFManager:
    """Manages PF state flushing for blocked domains"""
    
    def __init__(self):
        # Check if we have pfctl available
        self.pfctl_path = self._find_pfctl()
        if not self.pfctl_path:
            logger.warning("pfctl not found - PF state flushing will be disabled")
    
    def _find_pfctl(self) -> Optional[str]:
        """Find pfctl binary"""
        try:
            result = subprocess.run(
                ['which', 'pfctl'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        
        # Try common location
        common_path = '/sbin/pfctl'
        try:
            subprocess.run(
                [common_path, '-s', 'info'],
                capture_output=True,
                check=False
            )
            return common_path
        except Exception:
            pass
            
        return None
    
    def flush_states(self, ips: List[str]):
        """Flush PF states for given IPs"""
        if not self.pfctl_path:
            return
        
        if not ips:
            return
            
        # Build pfctl command to kill states
        # Note: This requires root privileges
        for ip in ips:
            try:
                # Kill states to/from this IP
                cmds = [
                    # Kill states where source is the IP
                    [self.pfctl_path, '-k', ip],
                    # Kill states where destination is the IP
                    [self.pfctl_path, '-k', f'0.0.0.0/0', '-k', ip]
                ]
                
                for cmd in cmds:
                    result = subprocess.run(
                        ['sudo', '-n'] + cmd,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if result.returncode == 0:
                        logger.debug(f"Flushed PF states for {ip}")
                    else:
                        if 'sudo: a password is required' in result.stderr:
                            logger.error("ERROR: PF state flushing failed - alwaysblockd must be run with sudo")
                            logger.error("Run: sudo alwaysblockd")
                            raise RuntimeError("PF state flushing requires sudo")
                        else:
                            logger.error(f"Failed to flush PF states: {result.stderr}")
                            
            except Exception as e:
                logger.debug(f"Failed to flush PF states for {ip}: {e}")
    
    def flush_all_states(self):
        """Flush all PF states"""
        if not self.pfctl_path:
            return
            
        try:
            # Flush all states
            result = subprocess.run(
                ['sudo', '-n', self.pfctl_path, '-F', 'states'],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("Flushed all PF states")
            elif 'sudo: a password is required' in result.stderr:
                logger.error("ERROR: PF state flushing failed - alwaysblockd must be run with sudo")
                logger.error("Run: sudo alwaysblockd")
                raise RuntimeError("PF state flushing requires sudo")
            else:
                logger.error(f"Failed to flush all PF states: {result.stderr}")
                
        except Exception as e:
            logger.debug(f"Failed to flush all PF states: {e}")