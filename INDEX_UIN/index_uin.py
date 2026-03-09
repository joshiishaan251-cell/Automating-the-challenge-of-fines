import os
import glob
import yaml
import logging
import concurrent.futures
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path to support both standalone and orchestrator runs
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from INDEX_UIN.db_manager import DBManager
from INDEX_UIN.scanner import ArchiveScanner
from INDEX_UIN.report_generator import ReportGenerator

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UIN_Indexer")


def load_config(config_path=None):
    if config_path is None:
        if os.path.exists("uin_indexer_config.yaml"):
            config_path = "uin_indexer_config.yaml"
        else:
            config_path = Path(__file__).resolve().parent / "uin_indexer_config.yaml"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Resolve db_path from config dir (it's internal to the module)
        # e.g. 'INDEX_UIN/uin_index.db' in config → resolved relative to the dir that CONTAINS config
        config_dir = Path(config_path).resolve().parent
        db_path = config.get('db_path', 'INDEX_UIN/uin_index.db')
        if not os.path.isabs(db_path):
            # Config is inside INDEX_UIN/, so resolve from the PARENT of config_dir
            # to get <project_root>/INDEX_UIN/uin_index.db
            config['db_path'] = str((config_dir.parent / db_path).resolve())

        # Resolve report_output from cwd (where the bat file is run — project root)
        # Users find reports relative to where they launch the tool
        report_output = config.get('report_output', 'reports/UIN_Duplicates_Report.xlsx')
        if not os.path.isabs(report_output):
            config['report_output'] = str((Path.cwd() / report_output).resolve())

        return config
    except Exception as e:
        logger.error(f"Failed to load config {config_path}: {e}")
        return None


def process_single_archive(archive_path, scanner, db_manager):
    """
    Worker function for parallel processing.
    Fix #1: Returns (count, hash_value) so the main loop can cache hashes
            without a second os.stat() pass during reconciliation.
    Fix #2: scan_archive now deduplicates internally, so count is accurate.
    """
    try:
        current_hash = scanner.get_archive_hash(archive_path)

        # Bug #2 fix: None hash means stat failed (e.g. transient network error).
        # Don't store None — it would permanently mark archive as "unchanged".
        # Skip this run; the archive will be retried on the next run.
        if current_hash is None:
            logger.warning(
                f"Could not hash {os.path.basename(archive_path)} "
                f"(stat error?) — skipping this run, will retry next time."
            )
            return 0, None

        # Atomic check-and-upsert — BEGIN IMMEDIATE in db_manager prevents race conditions
        archive_id, is_changed = db_manager.get_or_update_archive_atomic(archive_path, current_hash)

        if not is_changed:
            logger.debug(f"Skipping unchanged archive: {os.path.basename(archive_path)}")
            return 0, current_hash  # Return cached hash even for skipped files

        logger.info(f"Scanning archive: {os.path.basename(archive_path)}")
        found_uins = scanner.scan_archive(archive_path)

        if found_uins:
            db_manager.add_uin_occurrences_batch(found_uins, archive_id)
            return len(found_uins), current_hash

    except Exception as e:
        logger.error(f"Failed to process archive {archive_path}: {e}")
    return 0, None


def rotate_reports(report_dir, stem_name, ext, keep=30):
    """
    Fix #10: Delete oldest reports to keep at most `keep` files.
    Pattern: <report_dir>/<stem_name>_*.xlsx
    """
    pattern = os.path.join(report_dir, f'{stem_name}_*{ext}')
    try:
        existing = sorted(glob.glob(pattern), key=os.path.getmtime)
        to_delete = existing[:-keep] if len(existing) > keep else []
        for old_report in to_delete:
            try:
                os.remove(old_report)
                logger.info(f"Rotated old report: {os.path.basename(old_report)}")
            except OSError as e:
                logger.warning(f"Could not delete old report {old_report}: {e}")
    except Exception as e:
        logger.warning(f"Report rotation failed: {e}")


def main():
    logger.info("Starting UIN Indexer Pipeline...")

    config = load_config()
    if not config:
        return

    db_manager = DBManager(config['db_path'])
    scanner = ArchiveScanner(
        winrar_path=config.get('winrar_path'),
        file_extensions=config.get('file_extensions', []),
        exclude_prefixes=config.get('exclude_filename_prefixes', [])
    )

    # 0. Verify tools
    success, msg = scanner.verify_tools()
    if not success:
        logger.error(f"Tool verification failed: {msg}")
        return
    logger.info(msg)

    report_gen = ReportGenerator(db_manager)

    # 1. Find all sources (archives + loose files in subdirs)
    logger.info("Searching for archives and files...")
    archives = scanner.walk_and_find_sources(config['scan_paths'])
    total_archives = len(archives)
    logger.info(f"Found {total_archives} sources (ZIP/RAR archives + loose files).")

    # 2. Parallel scanning
    # Fix #1: collect hashes returned by workers — no second stat() pass needed
    total_uins_found = 0
    processed = 0
    hash_to_new_path = {}  # built from worker results, used for reconciliation
    max_workers = config.get('parallel_workers', 8)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_archive = {
            executor.submit(process_single_archive, arc, scanner, db_manager): arc
            for arc in archives
        }

        for future in concurrent.futures.as_completed(future_to_archive):
            processed += 1
            arc = future_to_archive[future]
            try:
                count, arc_hash = future.result()
                total_uins_found += count
                if arc_hash:
                    hash_to_new_path[arc_hash] = arc   # ← cache from first pass
            except Exception as e:
                logger.error(f"Worker crashed on {os.path.basename(arc)}: {e}")

            if processed % 10 == 0 or processed == total_archives:
                logger.info(f"Progress: {processed}/{total_archives} archives processed.")

    logger.info(f"Indexing complete. Total new UIN occurrences recorded: {total_uins_found}")

    # 2b. Reconciliation — uses cached hashes, no extra stat() calls
    logger.info("Reconciling archive paths (checking for moved/deleted files)...")
    db_manager.reconcile_archives(hash_to_new_path)
    logger.info("Reconciliation complete.")

    # 3. Generate report with datetime stamp
    base_path = config.get('report_output', 'reports/UIN_Duplicates_Report.xlsx')
    stem, ext = os.path.splitext(base_path)
    stem_name = os.path.basename(stem)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
    report_path = f"{stem}_{timestamp}{ext}"

    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    if report_gen.generate_excel_report(report_path):
        logger.info(f"Pipeline finished. Report available at: {os.path.abspath(report_path)}")
        # Fix #10: rotate old reports, keep last N (default 30)
        keep_reports = config.get('keep_reports', 30)
        rotate_reports(report_dir, stem_name, ext, keep=keep_reports)
    else:
        logger.error("Failed to generate report.")


if __name__ == "__main__":
    main()
