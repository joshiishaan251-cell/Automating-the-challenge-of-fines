import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

class DBManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._connection() as conn:
            cursor = conn.cursor()
            
            # Archives table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE,
                    hash TEXT,
                    last_scanned DATETIME
                )
            ''')
            
            # UINs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT UNIQUE
                )
            ''')
            
            # Occurrences table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS occurrences (
                    uin_id INTEGER,
                    archive_id INTEGER,
                    filename TEXT,
                    discovery_date DATETIME,
                    FOREIGN KEY (uin_id) REFERENCES uins(id),
                    FOREIGN KEY (archive_id) REFERENCES archives(id)
                )
            ''')
            
            # Indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_uin_number ON uins(number)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_occurrence_uin ON occurrences(uin_id)')
            
            conn.commit()

    def get_or_create_archive(self, path, archive_hash):
        now = datetime.now().isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM archives WHERE path = ?', (path,))
            row = cursor.fetchone()
            if row:
                archive_id = row[0]
                cursor.execute('UPDATE archives SET hash = ?, last_scanned = ? WHERE id = ?',
                             (archive_hash, now, archive_id))
            else:
                cursor.execute('INSERT INTO archives (path, hash, last_scanned) VALUES (?, ?, ?)',
                             (path, archive_hash, now))
                archive_id = cursor.lastrowid
            conn.commit()
            return archive_id

    def add_uin_occurrence(self, uin_number, archive_id, filename):
        now = datetime.now().isoformat()
        with self._connection() as conn:
            cursor = conn.cursor()
            
            # Get or create UIN
            cursor.execute('SELECT id FROM uins WHERE number = ?', (uin_number,))
            row = cursor.fetchone()
            if row:
                uin_id = row[0]
            else:
                cursor.execute('INSERT INTO uins (number) VALUES (?)', (uin_number,))
                uin_id = cursor.lastrowid
            
            # Add occurrence
            cursor.execute('''
                INSERT INTO occurrences (uin_id, archive_id, filename, discovery_date)
                VALUES (?, ?, ?, ?)
            ''', (uin_id, archive_id, filename, now))
            
            conn.commit()
