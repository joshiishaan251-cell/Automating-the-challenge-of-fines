import os
import re
import shutil
import pdfplumber
import csv
import logging
import yaml
import argparse
from datetime import datetime
from pathlib import Path

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- DEFAULT CONFIG (used if no config file is found) ---
DEFAULT_SOURCE_FOLDER = r"C:\PATH\TO\YOUR\DOWNLOADS\fines"
DEFAULT_SEARCH_PATHS = [
    r"C:\PATH\TO\YOUR\DOCUMENTS\Archive_1",
    r"C:\PATH\TO\YOUR\DOCUMENTS\Archive_General"
]
REPORT_FILE = "Sorting_Report.csv"


def load_config(config_path=None):
    """Load configuration from YAML file if available, else use defaults."""
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return {
            'source_folder': data.get('source_folder', DEFAULT_SOURCE_FOLDER),
            'search_paths': data.get('search_paths', DEFAULT_SEARCH_PATHS),
            'dry_run': data.get('dry_run', False),
            'report_file': data.get('report_file', REPORT_FILE),
        }
    return {
        'source_folder': DEFAULT_SOURCE_FOLDER,
        'search_paths': DEFAULT_SEARCH_PATHS,
        'dry_run': False,
        'report_file': REPORT_FILE,
    }


def extract_contract_number(pdf_path):
    """Searches for contract number in PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text()
            if not text: return None
            # Pattern for № followed by number-month-year. 
            # Supports both Cyrillic № and Latin N.
            pattern = r"(?:№|N)\s*(\d{2,5}-\d{1,2}(?:-\d{1,4})?)"
            match = re.search(pattern, text)
            return match.group(1) if match else None
    except Exception as e:
        logger.warning(f"Error reading {pdf_path}: {e}")
        return None


def find_target_folder_in_paths(paths_list, contract_number):
    """Searches for contract file in all specified paths."""
    for root_path in paths_list:
        if not os.path.exists(root_path): continue
        for root, _, files in os.walk(root_path):
            for file in files:
                if contract_number in file:
                    return root
    return None


def safe_move(src, dest_folder, filename, dry_run=False):
    """
    Safely moves a file with overwrite protection.
    If a file with the same name already exists, adds a suffix _1, _2, etc.
    Returns (success, final_path).
    """
    dest_path = os.path.join(dest_folder, filename)
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_folder, f"{base}_{counter}{ext}")
        counter += 1

    final_name = os.path.basename(dest_path)

    if dry_run:
        logger.info(f"[DRY RUN] {filename} -> {dest_path}")
        return True, final_name

    try:
        shutil.move(src, dest_path)
        return True, final_name
    except Exception as e:
        logger.error(f"Error moving {filename}: {e}")
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Payment Sorter")
    parser.add_argument('--dry-run', action='store_true', help="Simulation mode (no moving)")
    parser.add_argument('--config', type=str, default=None, help="Path to YAML config")
    args, _ = parser.parse_known_args()

    cfg = load_config(args.config)
    dry_run = args.dry_run or cfg.get('dry_run', False)
    source_folder = cfg['source_folder']
    search_paths = cfg['search_paths']
    report_file = cfg['report_file']

    if dry_run:
        print("[!] DRY RUN MODE (files are NOT moved)")

    results_for_csv = []
    print(f"{'PAYMENT FILE':<40} | {'NUMBER':<15} | {'STATUS'}")
    print("-" * 100)

    if not os.path.exists(source_folder):
        print(f"Error: Folder not found -> {source_folder}")
        return

    files = [f for f in os.listdir(source_folder) if f.lower().endswith('.pdf')]

    for filename in files:
        file_path = os.path.join(source_folder, filename)
        contract_num = extract_contract_number(file_path)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not contract_num:
            results_for_csv.append([current_time, filename, "---", "Error: Number not found", "---"])
            print(f"{filename[:40]:<40} | {'---':<15} | ❌ Number not found")
            continue

        target_folder = find_target_folder_in_paths(search_paths, contract_num)

        if target_folder:
            success, final_name = safe_move(file_path, target_folder, filename, dry_run=dry_run)
            if success:
                print(f"{filename[:40]:<40} | {contract_num:<15} | ✅ {'[DRY] ' if dry_run else ''}Found")
                results_for_csv.append([current_time, filename, contract_num, "Successfully moved" if not dry_run else "DRY RUN", target_folder])
            else:
                print(f"{filename[:40]:<40} | {contract_num:<15} | ❌ Error: {final_name}")
                results_for_csv.append([current_time, filename, contract_num, f"Error: {final_name}", target_folder])
        else:
            print(f"{filename[:40]:<40} | {contract_num:<15} | ❌ Not found in archive")
            results_for_csv.append([current_time, filename, contract_num, "Error: Not found in archive", "---"])

    # SAVE REPORT TO CSV
    try:
        with open(report_file, mode="w", encoding="utf-16", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["Date/Time", "Payment File", "Contract Number", "Result", "Target Path"])
            writer.writerows(results_for_csv)
        print("-" * 100)
        print(f"Done! Report saved here: {os.path.abspath(report_file)}")
    except Exception as e:
        logger.error(f"Report write error: {e}. File might be open in Excel.")

if __name__ == "__main__":
    main()