import unittest
import os
import shutil
import yaml
import sqlite3
import zipfile
from pathlib import Path
import sys

# Ensure the module can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from INDEX_UIN.index_uin import main as index_main

class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.work_dir = Path("integration_test")
        self.work_dir.mkdir(exist_ok=True)
        
        self.assets_dir = self.work_dir / "assets"
        self.assets_dir.mkdir(exist_ok=True)
        
        # Create mock archives
        self.zip1 = self.assets_dir / "arc1.zip"
        with zipfile.ZipFile(self.zip1, 'w') as zf:
            zf.writestr("18800000000000000001.pdf", "data")
            zf.writestr("18800000000000000002.pdf", "data")
            
        self.zip2 = self.assets_dir / "arc2.zip"
        with zipfile.ZipFile(self.zip2, 'w') as zf:
            zf.writestr("DUP 18800000000000000001.pdf", "data") # Duplicate
            
        # Remove pre-existing db to ensure fresh run
        db_path = self.work_dir / "test.db"
        if db_path.exists():
            os.remove(db_path)

        # Create config
        self.config_path = self.work_dir / "uin_indexer_config.yaml"
        config = {
            "scan_paths": [str(self.assets_dir.absolute())],
            "db_path": str(db_path.absolute()),
            "report_output": str((self.work_dir / "report.xlsx").absolute()),
            "parallel_workers": 2
        }
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f)

    def tearDown(self):
        # Move out of the directory before trying to delete it
        os.chdir(getattr(self, 'old_cwd', os.getcwd()))
        
        # Give some time for SQLite connections to close and GC to run
        import gc
        import time
        gc.collect()
        time.sleep(0.5)
        
        if self.work_dir.exists():
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f"Warning: could not cleanup {self.work_dir}: {e}")

    def test_pipeline_execution(self):
        # Change dir to integration_test to let script find its uin_indexer_config.yaml
        self.old_cwd = os.getcwd()
        os.chdir(self.work_dir)
        try:
            index_main()
            
            # Verify DB content
            with sqlite3.connect("test.db") as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT number FROM uins")
                uins = [r[0] for r in cursor.fetchall()]
                self.assertIn("18800000000000000001", uins)
                self.assertIn("18800000000000000002", uins)
                
                cursor.execute("SELECT COUNT(*) FROM occurrences WHERE uin_id = (SELECT id FROM uins WHERE number='18800000000000000001')")
                self.assertEqual(cursor.fetchone()[0], 2) # Should find in both archives
            
            # Verify a timestamped report was created (e.g. report_2026-03-08_02-14.xlsx)
            import glob
            report_files = glob.glob("report_*.xlsx")
            self.assertTrue(
                len(report_files) > 0,
                "Expected at least one timestamped report file (report_*.xlsx)"
            )
            
        finally:
            if hasattr(self, 'old_cwd'):
                os.chdir(self.old_cwd)

if __name__ == "__main__":
    unittest.main()
