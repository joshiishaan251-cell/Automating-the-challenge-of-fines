import unittest
import os
import shutil
import sqlite3
import sys

# Ensure the module can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from INDEX_UIN.db_manager import DBManager

class TestDBManager(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_uin_index.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = DBManager(self.db_path)

    def tearDown(self):
        import gc, time
        del self.db
        gc.collect()
        time.sleep(0.3)
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            wal = self.db_path + '-wal'
            shm = self.db_path + '-shm'
            if os.path.exists(wal): os.remove(wal)
            if os.path.exists(shm): os.remove(shm)
        except PermissionError:
            pass

    def test_tables_created(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check for tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        self.assertIn('archives', tables)
        self.assertIn('uins', tables)
        self.assertIn('occurrences', tables)
        conn.close()

    def test_add_uin_occurrence(self):
        archive_id, _ = self.db.get_or_update_archive_atomic("\\\\System13\\y\\archive1.zip", "hash123")
        self.db.add_uin_occurrences_batch(
            [{'number': '10673342253419066540', 'filename': 'doc1.pdf'}],
            archive_id
        )
        
        # Verify
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT number FROM uins").fetchone()[0],
                "10673342253419066540"
            )
            self.assertEqual(
                conn.execute("SELECT filename FROM occurrences").fetchone()[0],
                "doc1.pdf"
            )

if __name__ == "__main__":
    unittest.main()
