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
            zf.writestr("10000000000000000001.pdf", "data")
            zf.writestr("10000000000000000002.pdf", "data")
            
        self.zip2 = self.assets_dir / "arc2.zip"
        with zipfile.ZipFile(self.zip2, 'w') as zf:
            zf.writestr("DUP 10000000000000000001.pdf", "data") # Duplicate
            
        # Create config
        self.config_path = self.work_dir / "uin_indexer_config.yaml"
        config = {
            "scan_paths": [str(self.assets_dir.absolute())],
            "db_path": str((self.work_dir / "test.db").absolute()),
            "report_output": str((self.work_dir / "report.xlsx").absolute()),
            "parallel_workers": 2
        }
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f)

    def tearDown(self):
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def test_pipeline_execution(self):
        # Change dir to integration_test to let script find its uin_indexer_config.yaml
        old_cwd = os.getcwd()
        os.chdir(self.work_dir)
        try:
            index_main()
            
            # Verify DB content
            conn = sqlite3.connect("test.db")
            cursor = conn.cursor()
            
            cursor.execute("SELECT number FROM uins")
            uins = [r[0] for r in cursor.fetchall()]
            self.assertIn("10000000000000000001", uins)
            self.assertIn("10000000000000000002", uins)
            
            cursor.execute("SELECT COUNT(*) FROM occurrences WHERE uin_id = (SELECT id FROM uins WHERE number='10000000000000000001')")
            self.assertEqual(cursor.fetchone()[0], 2) # Should find in both archives
            
            conn.close()
            
            # Verify report exists
            self.assertTrue(os.path.exists("report.xlsx"))
            
        finally:
            os.chdir(old_cwd)

if __name__ == "__main__":
    unittest.main()
