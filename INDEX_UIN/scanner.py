import os
import re
import zipfile
import logging
from pathlib import Path
from datetime import datetime
import hashlib

try:
    import rarfile
except ImportError:
    rarfile = None

logger = logging.getLogger(__name__)

class ArchiveScanner:
    def __init__(self, winrar_path=None):
        self.uin_pattern = re.compile(r'(\d{20,29})')
        if rarfile and winrar_path and os.path.exists(winrar_path):
            rarfile.tool_path = winrar_path

    def extract_uin(self, filename):
        """Extract UIN (20-29 digits) from a filename."""
        match = self.uin_pattern.search(filename)
        return match.group(1) if match else None

    def get_archive_hash(self, path):
        """Generate a lightweight hash based on file size and mtime."""
        try:
            stat = os.stat(path)
            # Combine size and mtime for a quick thumbprint
            raw_id = f"{path}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(raw_id.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error hashing archive {path}: {e}")
            return None

    def scan_archive(self, path):
        """Scan a ZIP or RAR archive for UINs in filenames."""
        results = []
        ext = os.path.splitext(path)[1].lower()
        
        try:
            if ext == '.zip':
                with zipfile.ZipFile(path, 'r') as zf:
                    for name in zf.namelist():
                        uin = self.extract_uin(os.path.basename(name))
                        if uin:
                            results.append({
                                'number': uin,
                                'filename': os.path.basename(name)
                            })
            elif ext == '.rar':
                if not rarfile:
                    logger.error(f"Cannot parse {path}: rarfile library not installed.")
                    return []
                with rarfile.RarFile(path, 'r') as rf:
                    for name in rf.namelist():
                        uin = self.extract_uin(os.path.basename(name))
                        if uin:
                            results.append({
                                'number': uin,
                                'filename': os.path.basename(name)
                            })
        except Exception as e:
            logger.error(f"Error scanning archive {path}: {e}")
            
        return results

    def walk_and_find_archives(self, root_paths):
        """Recursively find all .zip and .rar files in the given paths."""
        archives = []
        for root_path in root_paths:
            if not os.path.exists(root_path):
                logger.warning(f"Path does not exist: {root_path}")
                continue
                
            for root, _, files in os.walk(root_path):
                for file in files:
                    if file.lower().endswith(('.zip', '.rar')):
                        archives.append(os.path.join(root, file))
        return archives
