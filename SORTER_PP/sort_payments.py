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
DEFAULT_SOURCE_FOLDER = r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА\! пп 180 000"
DEFAULT_SEARCH_PATHS = [
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА\1 ИЛ",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА"
]
REPORT_FILE = "Otchet_Sortirovki.csv"


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
    """Ищет номер договора в PDF"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text()
            if not text: return None
            pattern = r"№\s*(\d{2,5}-\d{1,2}(?:-\d{1,4})?)"
            match = re.search(pattern, text)
            return match.group(1) if match else None
    except Exception as e:
        logger.warning(f"Ошибка чтения {pdf_path}: {e}")
        return None


def find_target_folder_in_paths(paths_list, contract_number):
    """Ищет файл договора во всех указанных путях"""
    for root_path in paths_list:
        if not os.path.exists(root_path): continue
        for root, _, files in os.walk(root_path):
            for file in files:
                if contract_number in file:
                    return root
    return None


def safe_move(src, dest_folder, filename, dry_run=False):
    """
    Безопасное перемещение файла с защитой от перезаписи.
    Если файл с таким именем уже существует — добавляет суффикс _1, _2, ...
    Возвращает (success, final_path).
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
        logger.error(f"Ошибка перемещения {filename}: {e}")
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Сортировщик платежек")
    parser.add_argument('--dry-run', action='store_true', help="Режим симуляции (без перемещения)")
    parser.add_argument('--config', type=str, default=None, help="Путь к YAML-конфигу")
    args, _ = parser.parse_known_args()

    cfg = load_config(args.config)
    dry_run = args.dry_run or cfg.get('dry_run', False)
    source_folder = cfg['source_folder']
    search_paths = cfg['search_paths']
    report_file = cfg['report_file']

    if dry_run:
        print("[!] РЕЖИМ DRY RUN (файлы НЕ перемещаются)")

    results_for_csv = []
    print(f"{'ФАЙЛ ПЛАТЕЖКИ':<40} | {'НОМЕР':<15} | {'СТАТУС'}")
    print("-" * 100)

    if not os.path.exists(source_folder):
        print(f"Ошибка: Папка не найдена -> {source_folder}")
        return

    files = [f for f in os.listdir(source_folder) if f.lower().endswith('.pdf')]

    for filename in files:
        file_path = os.path.join(source_folder, filename)
        contract_num = extract_contract_number(file_path)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not contract_num:
            results_for_csv.append([current_time, filename, "---", "Ошибка: Номер не найден", "---"])
            print(f"{filename[:40]:<40} | {'---':<15} | ❌ Номер не найден")
            continue

        target_folder = find_target_folder_in_paths(search_paths, contract_num)

        if target_folder:
            success, final_name = safe_move(file_path, target_folder, filename, dry_run=dry_run)
            if success:
                print(f"{filename[:40]:<40} | {contract_num:<15} | ✅ {'[DRY] ' if dry_run else ''}Найдено")
                results_for_csv.append([current_time, filename, contract_num, "Успешно перемещено" if not dry_run else "DRY RUN", target_folder])
            else:
                print(f"{filename[:40]:<40} | {contract_num:<15} | ❌ Ошибка: {final_name}")
                results_for_csv.append([current_time, filename, contract_num, f"Ошибка: {final_name}", target_folder])
        else:
            print(f"{filename[:40]:<40} | {contract_num:<15} | ❌ Не найден в архиве")
            results_for_csv.append([current_time, filename, contract_num, "Ошибка: Не найден в архиве", "---"])

    # СОХРАНЕНИЕ ОТЧЕТА В CSV
    try:
        with open(report_file, mode="w", encoding="utf-16", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["Дата/Время", "Файл платежки", "Номер договора", "Результат", "Путь назначения"])
            writer.writerows(results_for_csv)
        print("-" * 100)
        print(f"Готово! Отчет сохранен здесь: {os.path.abspath(report_file)}")
    except Exception as e:
        logger.error(f"Ошибка записи отчета: {e}. Возможно, файл открыт в Excel.")

if __name__ == "__main__":
    main()