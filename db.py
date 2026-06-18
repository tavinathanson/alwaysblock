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
                    target_name TEXT,       -- Original target name(s) requested (e.g., 'slack', 'gmail', or 'all')
                    status TEXT NOT NULL,   -- 'waiting_for_domain', 'pending', 'active', 'completed'
                    wait_minutes INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    start_at TIMESTAMP,  -- When session becomes active (NULL for waiting_for_domain)
                    end_at TIMESTAMP,     -- When session expires (NULL for waiting_for_domain)
                    has_override INTEGER DEFAULT 0  -- 1 if tag override applied, 0 otherwise
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    profile TEXT PRIMARY KEY,
                    last_used TIMESTAMP NOT NULL
                )
            """)

            # Durable key/value store for persistent state (e.g. pause_until).
            # Lives in the db (not /tmp) so an all-day disable survives reboots.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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

            # Migration: Add has_override column if it doesn't exist
            try:
                conn.execute("SELECT has_override FROM sessions LIMIT 1")
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                conn.execute("ALTER TABLE sessions ADD COLUMN has_override INTEGER DEFAULT 0")
                logger.info("Added has_override column to sessions table")

            # Migration: Add target_name column if it doesn't exist
            try:
                conn.execute("SELECT target_name FROM sessions LIMIT 1")
            except sqlite3.OperationalError:
                # Column doesn't exist, add it
                conn.execute("ALTER TABLE sessions ADD COLUMN target_name TEXT")
                logger.info("Added target_name column to sessions table")

            conn.commit()
    
    @contextmanager
    def _get_conn(self):
        """Get database connection context manager"""
        # Don't use PARSE_DECLTYPES to avoid deprecated datetime adapters
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        """Store a durable key/value setting"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a durable key/value setting (returns default if unset)"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row['value'] if row else default

    def delete_setting(self, key: str) -> None:
        """Remove a durable key/value setting"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()

    def _datetime_to_str(self, dt: datetime) -> str:
        """Convert datetime to ISO format string for storage"""
        return dt.isoformat()

    def _str_to_datetime(self, s: str) -> datetime:
        """Convert ISO format string to datetime"""
        return datetime.fromisoformat(s)
    
    def create_session(self, profile: str, domains: List[str],
                      wait_minutes: int, duration_minutes: int, has_override: bool = False,
                      target_name: str = None, independent: bool = False) -> int:
        """Create a new session

        If any of the domains are already in an active or pending session, this new session
        will be marked as 'waiting_for_domain' and won't calculate its start time until
        those domains become available. This ensures the wait time is calculated based on
        the state when the domain actually becomes free, not when the session is created.

        Args:
            profile: Profile name
            domains: List of domains to unblock
            wait_minutes: Minutes to wait before starting (stored for later use)
            duration_minutes: Minutes the session lasts
            has_override: True if this session has a tag-based wait override applied
            target_name: Original target name(s) requested (e.g., 'slack', 'gmail', or 'all')
            independent: If True, skip queueing check (runs concurrently with other sessions)
        """
        now = datetime.now()

        # Independent sessions never queue - they run concurrently with other sessions
        # Check if any of these domains are already in active/pending/waiting sessions
        domain_in_use = False if independent else self._check_domain_in_use(domains)

        if domain_in_use:
            # Domain is currently in use - mark as waiting, don't set start/end times yet
            status = 'waiting_for_domain'
            start_at = None
            end_at = None
            logger.info(f"Creating waiting session for {domains}: domain currently in use")
        else:
            # Domain is free - calculate start/end times normally
            start_at = now + timedelta(minutes=wait_minutes)
            end_at = start_at + timedelta(minutes=duration_minutes)

            # Session is active if it should start immediately
            status = 'active' if start_at <= now else 'pending'
            logger.info(f"Creating {'active' if status == 'active' else 'pending'} session for {domains}")

        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO sessions
                (profile, domains, target_name, status, wait_minutes, duration_minutes,
                 created_at, start_at, end_at, has_override)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile,
                json.dumps(domains),
                target_name,
                status,
                wait_minutes,
                duration_minutes,
                self._datetime_to_str(now),
                self._datetime_to_str(start_at) if start_at else None,
                self._datetime_to_str(end_at) if end_at else None,
                1 if has_override else 0
            ))
            conn.commit()

            session_id = cursor.lastrowid
            logger.info(f"Created session {session_id} (status: {status}, target: {target_name}) for profile '{profile}' with {len(domains)} domains")

            return session_id

    def _check_domain_in_use(self, domains: List[str]) -> bool:
        """Check if the exact same set of domains is in active/pending sessions (NOT waiting)

        Changed to only queue when requesting the exact same set of domains,
        not just any overlap. This allows concurrent sessions for different targets.
        """
        if not domains:
            return False

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT domains FROM sessions
                WHERE status IN ('pending', 'active')
            """).fetchall()

            request_domains = set(domains)
            for row in rows:
                session_domains = set(json.loads(row['domains']))
                # Only queue if it's the exact same set of domains
                if request_domains == session_domains:
                    return True

            return False
    
    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get currently active sessions"""
        now = datetime.now()

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'active'
                AND end_at > ?
                ORDER BY end_at
            """, (self._datetime_to_str(now),)).fetchall()

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
    
    def get_waiting_sessions(self) -> List[Dict[str, Any]]:
        """Get sessions waiting for domains to become available"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM sessions
                WHERE status = 'waiting_for_domain'
                ORDER BY created_at
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
            """, (self._datetime_to_str(now),)).fetchall()

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

    def activate_waiting_sessions(self) -> List[Dict[str, Any]]:
        """Check waiting sessions and transition them to pending/active if domains are now free"""
        from config_manager import ConfigManager

        activated = []
        waiting_sessions = self.get_waiting_sessions()

        if not waiting_sessions:
            return activated

        for session in waiting_sessions:
            # Check if this session's domains are still in use
            domains = session['domains']

            # Check if exact same set of domains is in use by OTHER sessions (not this one)
            domain_still_in_use = False
            with self._get_conn() as conn:
                rows = conn.execute("""
                    SELECT domains FROM sessions
                    WHERE status IN ('pending', 'active')
                    AND id != ?
                """, (session['id'],)).fetchall()

                request_domains = set(domains)
                for row in rows:
                    session_domains = set(json.loads(row['domains']))
                    # Only wait if it's the exact same set of domains
                    if request_domains == session_domains:
                        domain_still_in_use = True
                        break

            if not domain_still_in_use:
                # Domain is free! Calculate timing NOW based on current state
                # We need to recalculate wait time based on current pending sessions
                now = datetime.now()

                # Use the stored wait_minutes - in practice this should be recalculated
                # by the config manager based on current concurrent sessions
                wait_minutes = session['wait_minutes']
                duration_minutes = session['duration_minutes']

                start_at = now + timedelta(minutes=wait_minutes)
                end_at = start_at + timedelta(minutes=duration_minutes)
                status = 'active' if start_at <= now else 'pending'

                with self._get_conn() as conn:
                    conn.execute("""
                        UPDATE sessions
                        SET status = ?, start_at = ?, end_at = ?
                        WHERE id = ?
                    """, (status, self._datetime_to_str(start_at),
                          self._datetime_to_str(end_at), session['id']))
                    conn.commit()

                session['status'] = status
                session['start_at'] = start_at
                session['end_at'] = end_at
                activated.append(session)
                logger.info(f"Activated waiting session {session['id']} -> {status}")

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
            """, (self._datetime_to_str(now),)).fetchall()
            
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
                AND status IN ('waiting_for_domain', 'pending', 'active')
            """, (session_id,))
            conn.commit()

            if result.rowcount > 0:
                logger.info(f"Cancelled session {session_id}")
                return True
            return False
    
    def count_concurrent_pending(self, profile: str) -> int:
        """Count pending sessions for concurrent penalty calculation

        Only counts sessions without tag-based overrides, so that override sessions
        (like gmail/slack with 1-min wait) don't inflate the penalty for normal sessions.
        """
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as count
                FROM sessions
                WHERE profile = ?
                AND status = 'pending'
                AND has_override = 0
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
            """, (profile, self._datetime_to_str(cooldown_until))).fetchone()

            if row:
                # Still on cooldown
                last_used = self._str_to_datetime(row['last_used'])
                remaining = (last_used + timedelta(minutes=cooldown_minutes)) - now
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
            """, (profile, self._datetime_to_str(now)))
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
        # Convert datetime strings to datetime objects
        for field in ['created_at', 'start_at', 'end_at', 'last_used']:
            if field in d and isinstance(d[field], str):
                d[field] = self._str_to_datetime(d[field])
        return d