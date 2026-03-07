import unittest
import os
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
        # Explicitly delete to force close if needed
        del self.db
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
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
        archive_id = self.db.get_or_create_archive("\\\\System13\\y\\archive1.zip", "hash123")
        self.db.add_uin_occurrence("10673342253419066540", archive_id, "doc1.pdf")
        
        # Verify
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT number FROM uins")
        self.assertEqual(cursor.fetchone()[0], "10673342253419066540")
        
        cursor.execute("SELECT filename FROM occurrences")
        self.assertEqual(cursor.fetchone()[0], "doc1.pdf")
        
        conn.close()

if __name__ == "__main__":
    unittest.main()
