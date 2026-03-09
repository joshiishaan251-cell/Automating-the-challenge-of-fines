import sqlite3
import os
import time
import random
from datetime import datetime
from contextlib import contextmanager

# Increment when schema changes
SCHEMA_VERSION = 2


class DBManager:
    def __init__(self, db_path):
        self.db_path = db_path
        # Fix #9: guard against dirname returning empty string
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        """Context manager with retry on SQLite lock.
        Uses isolation_level=None (autocommit) — all transactions are managed
        explicitly with BEGIN / COMMIT / ROLLBACK for precise control."""
        max_retries = 5
        base_delay = 0.1
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(
                    self.db_path, timeout=10, isolation_level=None
                )
                try:
                    yield conn
                finally:
                    conn.close()
                return
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.1))
                    continue
                raise

    def _get_schema_version(self, conn):
        return conn.execute("PRAGMA user_version").fetchone()[0]

    def _set_schema_version(self, conn, version):
        conn.execute(f"PRAGMA user_version = {version}")

    def _init_db(self):
        """Create or migrate tables to the current schema version."""
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = self._get_schema_version(conn)
            conn.execute("BEGIN IMMEDIATE")  # Fix #3: IMMEDIATE for schema writes
            try:
                if version < 1:
                    self._migrate_to_v1(conn)
                if version < 2:
                    self._migrate_to_v2(conn)
                self._set_schema_version(conn, SCHEMA_VERSION)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ── Migration v0 → v1 ────────────────────────────────────────────────
    def _migrate_to_v1(self, conn):
        conn.execute('''
            CREATE TABLE IF NOT EXISTS archives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                hash TEXT,
                last_scanned DATETIME
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS uins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE
            )
        ''')
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='occurrences'"
        ).fetchone()
        if existing:
            has_unique = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='occurrences' AND name='idx_occ_unique'"
            ).fetchone()
            if not has_unique:
                conn.execute("ALTER TABLE occurrences RENAME TO occurrences_old")
                self._create_occurrences(conn)
                conn.execute('''
                    INSERT OR IGNORE INTO occurrences (uin_id, archive_id, filename, discovery_date)
                    SELECT DISTINCT uin_id, archive_id, filename, discovery_date
                    FROM occurrences_old
                ''')
                conn.execute("DROP TABLE occurrences_old")
        else:
            self._create_occurrences(conn)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_uin_number ON uins(number)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_occurrence_uin ON occurrences(uin_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_occurrence_archive ON occurrences(archive_id)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_occ_unique ON occurrences(uin_id, archive_id, filename)')

    def _create_occurrences(self, conn):
        conn.execute('''
            CREATE TABLE occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uin_id INTEGER,
                archive_id INTEGER,
                filename TEXT,
                discovery_date DATETIME,
                FOREIGN KEY (uin_id) REFERENCES uins(id),
                FOREIGN KEY (archive_id) REFERENCES archives(id),
                UNIQUE (uin_id, archive_id, filename)
            )
        ''')

    # ── Migration v1 → v2: add moved_to + is_available ───────────────────
    def _migrate_to_v2(self, conn):
        existing_cols = [
            row[1] for row in conn.execute("PRAGMA table_info(archives)").fetchall()
        ]
        if 'is_available' not in existing_cols:
            conn.execute("ALTER TABLE archives ADD COLUMN is_available INTEGER DEFAULT 1")
        if 'moved_to' not in existing_cols:
            conn.execute("ALTER TABLE archives ADD COLUMN moved_to TEXT")

    # ── Atomic archive upsert ─────────────────────────────────────────────
    def get_or_update_archive_atomic(self, path, current_hash):
        """
        Fix #3: Uses BEGIN IMMEDIATE to get a RESERVED lock upfront,
        preventing write conflicts between threads in WAL mode.
        Returns (archive_id, is_changed).
        """
        now = datetime.now().isoformat()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO archives (path, hash, last_scanned, is_available) '
                    'VALUES (?, ?, ?, 1)',
                    (path, None, now)
                )
                row = conn.execute(
                    'SELECT id, hash FROM archives WHERE path = ?', (path,)
                ).fetchone()
                archive_id, stored_hash = row
                is_changed = stored_hash != current_hash
                if is_changed:
                    conn.execute(
                        'UPDATE archives SET hash = ?, last_scanned = ?, '
                        'is_available = 1, moved_to = NULL WHERE id = ?',
                        (current_hash, now, archive_id)
                    )
                conn.execute("COMMIT")
                return archive_id, is_changed
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ── Reconciliation: mark missing archives ─────────────────────────────
    def reconcile_archives(self, hash_to_new_path):
        """
        Fix #5: Check every DB archive path against the filesystem.
        Uses batched SQL: one WHERE IN (...) for available archives,
        executemany for unavailable — drastically fewer round trips.
        """
        with self._connection() as conn:
            rows = conn.execute('SELECT id, path, hash FROM archives').fetchall()

            available_ids = []
            unavailable_updates = []  # [(moved_to, archive_id), ...]

            for archive_id, path, stored_hash in rows:
                if os.path.exists(path):
                    available_ids.append(archive_id)
                else:
                    new_path = hash_to_new_path.get(stored_hash) if stored_hash else None
                    moved_to = new_path if new_path else 'path not found'
                    unavailable_updates.append((moved_to, archive_id))

            conn.execute("BEGIN")
            try:
                # Single UPDATE for all available archives
                if available_ids:
                    placeholders = ','.join('?' * len(available_ids))
                    conn.execute(
                        f'UPDATE archives SET is_available=1, moved_to=NULL '
                        f'WHERE id IN ({placeholders})',
                        available_ids
                    )
                # executemany for unavailable (one transaction, N UPDATE statements)
                if unavailable_updates:
                    conn.executemany(
                        'UPDATE archives SET is_available=0, moved_to=? WHERE id=?',
                        unavailable_updates
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ── Batch UIN insert ──────────────────────────────────────────────────
    def add_uin_occurrences_batch(self, uin_items, archive_id):
        """Add UIN occurrences in one transaction.
        Fix #3: Uses BEGIN IMMEDIATE to avoid "database is locked" under 8+ workers."""
        now = datetime.now().isoformat()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")  # Fix #3: was DEFERRED BEGIN
            try:
                for item in uin_items:
                    conn.execute(
                        'INSERT OR IGNORE INTO uins (number) VALUES (?)', (item['number'],)
                    )
                    uin_id = conn.execute(
                        'SELECT id FROM uins WHERE number = ?', (item['number'],)
                    ).fetchone()[0]
                    conn.execute('''
                        INSERT OR IGNORE INTO occurrences (uin_id, archive_id, filename, discovery_date)
                        VALUES (?, ?, ?, ?)
                    ''', (uin_id, archive_id, item['filename'], now))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def add_uin_occurrence(self, uin_number, archive_id, filename):
        """Single-item shim."""
        self.add_uin_occurrences_batch(
            [{'number': uin_number, 'filename': filename}], archive_id
        )
