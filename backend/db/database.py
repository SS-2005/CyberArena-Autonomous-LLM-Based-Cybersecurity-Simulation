import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from backend.configs.settings import resolve_project_root, settings
from backend.utils.logger import logger


class Database:
    """
    Thread-safe SQLite database manager for CyberArena.
    Handles schema initialization, WAL mode, foreign keys, and connection lifecycle.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._is_memory = False
        self._keepalive_conn: Optional[sqlite3.Connection] = None

        if db_path == ":memory:":
            self._is_memory = True
            # Unique shared in-memory URI so tests don't collide but threads share same DB
            mem_id = threading.get_ident()
            self.db_path = f"file:cyberarena_mem_{id(self)}?mode=memory&cache=shared"
            self._keepalive_conn = sqlite3.connect(self.db_path, uri=True, check_same_thread=False)
        elif db_path:
            self.db_path = str(Path(db_path).resolve())
        else:
            root = resolve_project_root()
            default_dir = root / "data"
            default_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(default_dir / "cyberarena.db")

        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection with optimal pragmas."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            if self._is_memory:
                conn = sqlite3.connect(
                    self.db_path,
                    uri=True,
                    timeout=30.0,
                    check_same_thread=False,
                )
            else:
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=30.0,
                    check_same_thread=False,
                )
            conn.row_factory = sqlite3.Row
            # Enable pragmas for performance and data integrity
            with conn:
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.execute("PRAGMA busy_timeout = 30000;")
                if not self._is_memory:
                    conn.execute("PRAGMA journal_mode = WAL;")
                    conn.execute("PRAGMA synchronous = NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize tables and indexes if they do not already exist."""
        with self._lock:
            conn = self.get_connection()
            with conn:
                # 1. Experiments table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS experiments (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        status TEXT NOT NULL DEFAULT 'created',
                        config_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT,
                        error_message TEXT,
                        final_conclusion TEXT
                    );
                    """
                )

                # 2. Experiment Agents table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS experiment_agents (
                        id TEXT PRIMARY KEY,
                        experiment_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        vm_id TEXT NOT NULL,
                        model_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'idle',
                        iteration_limit INTEGER NOT NULL DEFAULT 10,
                        current_iteration INTEGER NOT NULL DEFAULT 0,
                        command_timeout INTEGER NOT NULL DEFAULT 60,
                        error_message TEXT,
                        final_conclusion TEXT,
                        history_json TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
                    );
                    """
                )

                # 3. Experiment Events table
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS experiment_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        experiment_id TEXT NOT NULL,
                        agent_id TEXT,
                        event_type TEXT NOT NULL,
                        iteration INTEGER DEFAULT 0,
                        timestamp TEXT NOT NULL,
                        tool_name TEXT,
                        content TEXT,
                        status TEXT,
                        error TEXT,
                        data_json TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
                    );
                    """
                )

                # Safe migrations for existing databases
                try:
                    conn.execute("ALTER TABLE experiments ADD COLUMN final_conclusion TEXT;")
                except Exception:
                    pass

                try:
                    conn.execute("ALTER TABLE experiment_agents ADD COLUMN final_conclusion TEXT;")
                except Exception:
                    pass

                # Indices
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_exp_agents_exp_id ON experiment_agents(experiment_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_exp_events_exp_id ON experiment_events(experiment_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_exp_events_timestamp ON experiment_events(timestamp);"
                )

            logger.info(f"Initialized SQLite database at {self.db_path}")

    def close(self) -> None:
        """Close current thread's connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None


# Global singleton instance
_default_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_database(db_path: Optional[str] = None) -> Database:
    global _default_db
    with _db_lock:
        if _default_db is None:
            _default_db = Database(db_path=db_path)
        return _default_db


def set_database(db: Optional[Database]) -> None:
    global _default_db
    with _db_lock:
        _default_db = db
