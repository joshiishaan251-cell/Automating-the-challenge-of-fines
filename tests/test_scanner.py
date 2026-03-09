import unittest
import os
import zipfile
import sys
from pathlib import Path

# Ensure the module can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from INDEX_UIN.scanner import ArchiveScanner

class TestArchiveScanner(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_assets")
        self.test_dir.mkdir(exist_ok=True)
        
        # Create a mock zip
        self.zip_path = self.test_dir / "test_archive.zip"
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("10673342253419066540.pdf", "data")
            # Using English 'Resolution' in test mock
            zf.writestr("Resolution 18873342253419066541.pdf", "data")
            zf.writestr("other.txt", "data")

    def tearDown(self):
        if self.zip_path.exists():
            os.remove(self.zip_path)
        if self.test_dir.exists():
            import shutil
            shutil.rmtree(self.test_dir)

    def test_extract_uins_from_zip(self):
        scanner = ArchiveScanner()
        uins = scanner.scan_archive(str(self.zip_path))
        
        # Check if both UINs are found
        uin_list = [u['number'] for u in uins]
        self.assertIn("10673342253419066540", uin_list)
        self.assertIn("18873342253419066541", uin_list)
        self.assertEqual(len(uins), 2)

    def test_regex_matching(self):
        scanner = ArchiveScanner()
        self.assertEqual(scanner.extract_uin("10673342253419066540.pdf"), "10673342253419066540")
        # Check both Russian and English prefixes if necessary, but English is priority now
        self.assertEqual(scanner.extract_uin("Resolution  10673342253419066540_copy.pdf"), "10673342253419066540")
        self.assertIsNone(scanner.extract_uin("short_123.pdf"))

if __name__ == "__main__":
    unittest.main()
