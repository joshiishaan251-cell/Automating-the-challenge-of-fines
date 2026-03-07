import os
import yaml
import logging
import concurrent.futures
from datetime import datetime
from INDEX_UIN.db_manager import DBManager
from INDEX_UIN.scanner import ArchiveScanner
from INDEX_UIN.report_generator import ReportGenerator

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UIN_Indexer")

def load_config(config_path="uin_indexer_config.yaml"):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config {config_path}: {e}")
        return None

def process_single_archive(archive_path, scanner, db_manager):
    """Worker function for parallel processing."""
    try:
        current_hash = scanner.get_archive_hash(archive_path)
        
        # Optimization: check hash in DB (could be implemented as a separate check to avoid opening DB many times)
        # For simplicity in this version, we scan if hash differs or is new.
        # Actually, get_or_create_archive does the update, so we can use it to decide.
        
        # Simple policy: scan all found archives for now, but log path.
        logger.info(f"Scanning archive: {os.path.basename(archive_path)}")
        found_uins = scanner.scan_archive(archive_path)
        
        if found_uins:
            archive_id = db_manager.get_or_create_archive(archive_path, current_hash)
            for item in found_uins:
                db_manager.add_uin_occurrence(item['number'], archive_id, item['filename'])
            return len(found_uins)
    except Exception as e:
        logger.error(f"Failed to process archive {archive_path}: {e}")
    return 0

def main():
    logger.info("Starting UIN Indexer Pipeline...")
    
    config = load_config()
    if not config:
        return

    db_manager = DBManager(config['db_path'])
    scanner = ArchiveScanner(winrar_path=config.get('winrar_path'))
    report_gen = ReportGenerator(db_manager)

    # 1. Find all archives
    logger.info("Searching for ZIP/RAR archives...")
    archives = scanner.walk_and_find_archives(config['scan_paths'])
    logger.info(f"Found {len(archives)} archives.")

    # 2. Parallel Scanning
    total_uins_found = 0
    max_workers = config.get('parallel_workers', 8)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a list of future tasks
        future_to_archive = {executor.submit(process_single_archive, arc, scanner, db_manager): arc for arc in archives}
        
        for future in concurrent.futures.as_completed(future_to_archive):
            result = future.result()
            total_uins_found += result

    logger.info(f"Indexing complete. Total UIN occurrences recorded: {total_uins_found}")

    # 3. Generate Report
    report_path = config.get('report_output', 'UIN_Duplicates_Report.xlsx')
    # Ensure directory exists
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    if report_gen.generate_excel_report(report_path):
        logger.info(f"Pipeline finished. Report available at: {os.path.abspath(report_path)}")
    else:
        logger.error("Failed to generate report.")

if __name__ == "__main__":
    main()
