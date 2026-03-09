import os
import re
import zipfile
import hashlib
import logging

try:
    import rarfile
except ImportError:
    rarfile = None

logger = logging.getLogger(__name__)

# ── Compiled patterns (module level for efficiency) ──────────────────────────

# Fix #7: Flexible separator between UIN digits and Russian date.
# Covers: space, underscore, dash — e.g. "10673...2084 21 june 2024"
#                                       or "10673...2084_21_june_2024"
# Note: re.match() anchors at start, so no leading ^ needed.
# Regex for Russian months (january, february, etc.) 
# Required for identifying and skipping Russian payment receipts.
_RECEIPT_DATE_RE = re.compile(
    r'^[\s_\-]+\d{1,2}[\s_\-]+'
    r'(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|'
    r'август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)'
    r'[\s_\-]+\d{4}'
)


class ArchiveScanner:
    def __init__(self, winrar_path=None, file_extensions=None, exclude_prefixes=None):
        self.uin_pattern = re.compile(r'(\d{20,29})')
        # Known UIN prefixes: 106=MADI, 188=GIBDD, 322=customs, 0355/0356=other
        self.valid_prefixes = ('106', '188', '322', '0355', '0356')
        # Extensions of loose files to scan alongside archives
        self.file_extensions = tuple(
            ext.lower() if ext.startswith('.') else f'.{ext.lower()}'
            for ext in (file_extensions or [])
        )
        # Filename prefixes to skip (case-insensitive), e.g. 'Check_'
        self.exclude_prefixes = tuple(
            p.lower() for p in (exclude_prefixes or [])
        )
        self.winrar_path = winrar_path
        if rarfile and winrar_path and os.path.exists(winrar_path):
            rarfile.tool_path = winrar_path

    def verify_tools(self):
        """Verify that WinRAR/UnRAR is available."""
        if not rarfile:
            return True, "rarfile library not installed, RAR support disabled."
        if not self.winrar_path:
            return True, "WinRAR path not configured. ZIPs will work, but RARs will fail if encountered."
        if os.path.exists(self.winrar_path):
            return True, f"WinRAR tool found: {self.winrar_path}"
        return False, f"WinRAR path configured but file not found: {self.winrar_path}"

    def extract_uin(self, filename):
        """Extract and validate a UIN from a filename.

        Returns None (skipped) when:
          1. Filename starts with an excluded prefix (e.g. 'Check_')
          2. Filename is a receipt: digits followed by Russian date/time
             e.g. '10673342243451842084 21 june 2024 15-41-04'
          3. The extracted number doesn't have a known UIN prefix
        """
        # ① Skip by filename pattern (prefix or substring)
        if self.exclude_prefixes:
            fn_low = filename.lower()
            for p in self.exclude_prefixes:
                # If pattern is *substring*, check if it's anywhere in the filename
                if p.startswith('*') and p.endswith('*') and len(p) > 2:
                    if p[1:-1] in fn_low:
                        logger.debug(f"Skipping file with excluded substring '{p[1:-1]}': {filename}")
                        return None
                # Otherwise, maintain backward compatibility: check prefix
                elif fn_low.startswith(p):
                    logger.debug(f"Skipping excluded-prefix file: {filename}")
                    return None

        match = self.uin_pattern.search(filename)
        if not match:
            return None

        uin = match.group(1)
        # Lowercase for Cyrillic-safe match — re.IGNORECASE doesn't handle Cyrillic
        after_digits = filename[match.end():].lower()

        # ② Skip receipts: digits + separator + Russian day-month-year
        if _RECEIPT_DATE_RE.match(after_digits):
            logger.debug(f"Skipping receipt file (digits + Russian date): {filename}")
            return None

        # ③ Validate UIN prefix
        if uin.startswith(self.valid_prefixes):
            return uin

        logger.debug(f"Skipping number with unknown prefix: {uin}")
        return None

    def get_archive_hash(self, path):
        """Lightweight fingerprint: MD5 of (path + file size + mtime)."""
        try:
            stat = os.stat(path)
            return hashlib.md5(f"{path}_{stat.st_size}_{stat.st_mtime}".encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error hashing {path}: {e}")
            return None

    def scan_archive(self, path):
        """Scan a source for UINs in filenames.
        Supports ZIP, RAR archives, and loose files (e.g. PDF).

        Fix #2: Deduplicates results by (number, filename) before returning,
        so the counter in index_uin.py is accurate even if the same filename
        appears in multiple subdirectories of an archive.
        """
        results = []
        seen = set()  # (uin, basename) dedup set
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == '.zip':
                with zipfile.ZipFile(path, 'r') as zf:
                    for name in zf.namelist():
                        base = os.path.basename(name)
                        uin = self.extract_uin(base)
                        if uin:
                            key = (uin, base)
                            if key not in seen:
                                seen.add(key)
                                results.append({'number': uin, 'filename': base})
            elif ext == '.rar':
                if not rarfile:
                    logger.error(f"Cannot parse {path}: rarfile not installed.")
                    return []
                with rarfile.RarFile(path, 'r') as rf:
                    for name in rf.namelist():
                        base = os.path.basename(name)
                        uin = self.extract_uin(base)
                        if uin:
                            key = (uin, base)
                            if key not in seen:
                                seen.add(key)
                                results.append({'number': uin, 'filename': base})
            else:
                # Loose file: check its own name
                base = os.path.basename(path)
                uin = self.extract_uin(base)
                if uin:
                    results.append({'number': uin, 'filename': base})
        except Exception as e:
            logger.error(f"Error scanning {path}: {e}")
        return results

    def walk_and_find_sources(self, root_paths):
        """Recursively find archives (.zip, .rar) and loose files matching file_extensions."""
        archive_exts = ('.zip', '.rar')
        sources = []
        for root_path in root_paths:
            if not os.path.exists(root_path):
                logger.warning(f"Path does not exist: {root_path}")
                continue
            for root, _, files in os.walk(root_path):
                for file in files:
                    low = file.lower()
                    if low.endswith(archive_exts):
                        sources.append(os.path.join(root, file))
                    elif self.file_extensions and low.endswith(self.file_extensions):
                        sources.append(os.path.join(root, file))
        return sources

    # Backward-compat alias
    def walk_and_find_archives(self, root_paths):
        return self.walk_and_find_sources(root_paths)
