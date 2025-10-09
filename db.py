"""
Database management for alwaysblock
Tracks sessions, cooldowns, and timing state
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import json

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for session and cooldown tracking"""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / '.alwaysblock' / 'alwaysblock.db'
        
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile TEXT NOT NULL,
                    domains TEXT NOT NULL,  -- JSON array
                    status TEXT NOT NULL,   -- 'pending', 'active', 'completed'
                    wait_minutes INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    start_at TIMESTAMP NOT NULL,  -- When session becomes active
                    end_at TIMESTAMP NOT NULL     -- When session expires
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    profile TEXT PRIMARY KEY,
                    last_used TIMESTAMP NOT NULL
                )
            """)
            
            # Indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_status 
                ON sessions(status)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_start_at 
                ON sessions(start_at)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_end_at 
                ON sessions(end_at)
            """)
            
            conn.commit()
    
    @contextmanager
    def _get_conn(self):
        """Get database connection context manager"""
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def create_session(self, profile: str, domains: List[str], 
                      wait_minutes: int, duration_minutes: int) -> int:
        """Create a new session"""
        now = datetime.now()
        start_at = now + timedelta(minutes=wait_minutes)
        end_at = start_at + timedelta(minutes=duration_minutes)
        
        status = 'active' if wait_minutes == 0 else 'pending'
        
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO sessions 
                (profile, domains, status, wait_minutes, duration_minutes, 
                 created_at, start_at, end_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile, 
                json.dumps(domains),
                status,
                wait_minutes,
                duration_minutes,
                now,
                start_at,
                end_at
            ))
            conn.commit()
            
            session_id = cursor.lastrowid
            logger.info(f"Created session {session_id} for profile '{profile}' with {len(domains)} domains")
            
            return session_id
    
    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get currently active sessions"""
        now = datetime.now()
        
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'active' 
                AND end_at > ?
                ORDER BY end_at
            """, (now,)).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def get_pending_sessions(self) -> List[Dict[str, Any]]:
        """Get pending sessions (waiting to start)"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'pending'
                ORDER BY start_at
            """).fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def activate_pending_sessions(self) -> List[Dict[str, Any]]:
        """Check and activate any pending sessions that should start"""
        now = datetime.now()
        activated = []
        
        with self._get_conn() as conn:
            # Find sessions ready to activate
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'pending'
                AND start_at <= ?
            """, (now,)).fetchall()
            
            for row in rows:
                session = self._row_to_dict(row)
                
                # Update status to active
                conn.execute("""
                    UPDATE sessions
                    SET status = 'active'
                    WHERE id = ?
                """, (session['id'],))
                
                activated.append(session)
                logger.info(f"Activated session {session['id']}")
            
            conn.commit()
        
        return activated
    
    def expire_sessions(self) -> List[Dict[str, Any]]:
        """Mark expired sessions as completed"""
        now = datetime.now()
        expired = []
        
        with self._get_conn() as conn:
            # Find expired active sessions
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'active'
                AND end_at <= ?
            """, (now,)).fetchall()
            
            for row in rows:
                session = self._row_to_dict(row)
                
                # Update status to completed
                conn.execute("""
                    UPDATE sessions
                    SET status = 'completed'
                    WHERE id = ?
                """, (session['id'],))
                
                expired.append(session)
                logger.info(f"Expired session {session['id']}")
            
            conn.commit()
        
        return expired
    
    def cancel_session(self, session_id: int) -> bool:
        """Cancel a session"""
        with self._get_conn() as conn:
            result = conn.execute("""
                UPDATE sessions
                SET status = 'completed'
                WHERE id = ?
                AND status IN ('pending', 'active')
            """, (session_id,))
            conn.commit()
            
            if result.rowcount > 0:
                logger.info(f"Cancelled session {session_id}")
                return True
            return False
    
    def count_concurrent_pending(self, profile: str) -> int:
        """Count pending sessions for concurrent penalty calculation"""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as count
                FROM sessions
                WHERE profile = ?
                AND status = 'pending'
            """, (profile,)).fetchone()
            
            return row['count'] if row else 0
    
    def check_cooldown(self, profile: str, cooldown_minutes: int) -> bool:
        """Check if profile is on cooldown"""
        if cooldown_minutes <= 0:
            return True  # No cooldown configured
        
        now = datetime.now()
        cooldown_until = now - timedelta(minutes=cooldown_minutes)
        
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT last_used FROM cooldowns
                WHERE profile = ?
                AND last_used > ?
            """, (profile, cooldown_until)).fetchone()
            
            if row:
                # Still on cooldown
                remaining = (row['last_used'] + timedelta(minutes=cooldown_minutes)) - now
                logger.info(f"Profile '{profile}' on cooldown for {remaining.total_seconds():.0f} seconds")
                return False
            
            return True
    
    def update_cooldown(self, profile: str):
        """Update last used time for cooldown tracking"""
        now = datetime.now()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cooldowns (profile, last_used)
                VALUES (?, ?)
            """, (profile, now))
            conn.commit()
    
    def get_all_domains_from_sessions(self) -> List[str]:
        """Get all unique domains from active sessions"""
        domains = set()
        
        for session in self.get_active_sessions():
            domains.update(session['domains'])
        
        return list(domains)
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert database row to dictionary"""
        d = dict(row)
        # Parse JSON domains field
        if 'domains' in d and isinstance(d['domains'], str):
            d['domains'] = json.loads(d['domains'])
        return d