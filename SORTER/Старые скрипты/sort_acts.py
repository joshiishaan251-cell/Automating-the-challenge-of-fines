import os
import re
import shutil
import csv
import subprocess

# --- 1. НАСТРОЙКИ (CONFIGURATION) ---

SOURCE_FOLDER = r"C:\Users\Logik\Downloads\платежи штрафы 21112024\Акты"

ARCHIVE_PATHS = [
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА\1 ИЛ",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив ОТКАЗЫ Штрафы\А Повтор"
]

# True = Тест (без перемещения), False = Работа
DRY_RUN = False

POPPLER_PATH = r"C:\poppler\Library\bin\pdftotext.exe"

# --- 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def normalize_year(year_str):
    """Превращает '25' в '2025'"""
    if len(year_str) == 2:
        return "20" + year_str
    return year_str

def clean_ocr_digits(text):
    """Исправляет ошибки OCR (З->3, О->0 и т.д.)"""
    if not text: return ""
    table = str.maketrans("ЗОБЧАSsg", "30644559") 
    return text.translate(table)

def get_text_from_pdf(pdf_path):
    try:
        cmd = [POPPLER_PATH, '-layout', '-enc', 'UTF-8', pdf_path, '-']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0: return None
        return result.stdout
    except:
        return None

def extract_case_from_string(text_string):
    """
    Вытаскивает номер дела (292245-2025) из любой строки (имени папки или файла).
    """
    keys = []
    # Ищем 5-7 цифр, разделитель, 2 или 4 цифры года
    # Паттерн ловит: "А40-12345-25", "12345 2025", "12345_2025"
    pattern = r'(?<!\d)(\d{5,7})\D{0,5}(202\d|2\d)(?!\d)'
    matches = re.findall(pattern, text_string)
    
    for m in matches:
        num = m[0]
        year = normalize_year(m[1])
        keys.append(f"{num}-{year}")
    
    return keys

def build_deep_archive_indices():
    """
    ГЛУБОКИЙ ПОИСК (DEEP SCAN).
    Проходит по всем подпапкам внутри ARCHIVE_PATHS.
    """
    print("--- ЗАПУСК ГЛУБОКОЙ ИНДЕКСАЦИИ (Deep Scan) ---")
    case_index = {} # {"292245-2025": "Путь_к_папке"}
    uin_index = {}  # {"1067...": "Путь_к_папке"}
    
    scanned_folders = 0
    
    for root_path in ARCHIVE_PATHS:
        if not os.path.exists(root_path): continue
        
        # os.walk - это и есть "Паук", который лезет во все глубины
        for current_root, dirs, files in os.walk(root_path):
            scanned_folders += 1
            if scanned_folders % 500 == 0:
                print(f"   Просмотрено папок: {scanned_folders}...", end='\r')

            # 1. Проверяем ИМЯ ПАПКИ (например "А35 А40-314238-2025 Сизова...")
            folder_name = os.path.basename(current_root)
            keys_from_folder = extract_case_from_string(folder_name)
            
            for key in keys_from_folder:
                # Если нашли номер дела в имени папки — запоминаем этот путь
                if key not in case_index:
                    case_index[key] = current_root

            # 2. Проверяем ФАЙЛЫ внутри (для УИН и подстраховки)
            for file in files:
                # А. Поиск УИН (длинные цифры в имени файла)
                name_clean = re.sub(r'\D', '', file)
                if len(name_clean) >= 20 and name_clean.startswith("106"):
                    uin_index[name_clean] = current_root
                
                # Б. Поиск номера дела в имени файла (если папка названа непонятно)
                # (Только если мы еще не знаем, чья это папка)
                file_keys = extract_case_from_string(file)
                for fk in file_keys:
                    if fk not in case_index:
                        case_index[fk] = current_root

    print(f"\n--- Индексация завершена ---")
    print(f"Найдено дел (по папкам и файлам): {len(case_index)}")
    print(f"Найдено постановлений (по УИН): {len(uin_index)}")
    print("-" * 60 + "\n")
    return case_index, uin_index

def extract_identifiers_from_text(text):
    """Извлекает номера дел и УИНы из текста скана"""
    found_cases = []
    found_uins = []
    if not text: return found_cases, found_uins
    
    clean_text = text.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
    while "  " in clean_text: clean_text = clean_text.replace("  ", " ")
    
    # 1. УИНы
    potential_uins = re.findall(r'(106[\d\s\-]{17,35})', clean_text)
    for p_uin in potential_uins:
        digits = re.sub(r'\D', '', p_uin)
        if len(digits) >= 20: found_uins.append(digits)

    # 2. Номера дел
    # А. Контекстный поиск (после слов Дело/№)
    keyword_matches = re.finditer(r'(?:Дело|N|№|Решение)', clean_text, re.IGNORECASE)
    for match in keyword_matches:
        snippet = clean_text[match.end():match.end()+50]
        snippet_fixed = clean_ocr_digits(snippet) # Лечим OCR (З->3)
        keys = extract_case_from_string(snippet_fixed)
        found_cases.extend(keys)

    # Б. Прямой поиск A40...
    std_matches = re.findall(r'40[\s\-\/\\]+(\d{5,7})[\s\-\/\\]+(\d{2,4})', clean_text)
    for m in std_matches:
        found_cases.append(f"{m[0]}-{normalize_year(m[1])}")

    return list(set(found_cases)), list(set(found_uins))

def find_sample_and_target(case_folder_path, found_identifiers):
    """Ищет '3 Заявление...' и '! Взыскано...'"""
    sample_file = None
    target_dir = case_folder_path
    
    try:
        items = os.listdir(case_folder_path)
        
        # 1. Ищем подпапку
        for item in items:
            if os.path.isdir(os.path.join(case_folder_path, item)):
                if item.startswith("3 Заявление в МТУ"):
                    target_dir = os.path.join(case_folder_path, item)
                    break
        
        # 2. Ищем файл-образец
        candidates = []
        # Проверяем корень
        for f in items:
            if os.path.isfile(os.path.join(case_folder_path, f)) and f.startswith("! Взыскано"):
                candidates.append(f)
        # Проверяем подпапку
        if target_dir != case_folder_path:
            for f in os.listdir(target_dir):
                if os.path.isfile(os.path.join(target_dir, f)) and f.startswith("! Взыскано"):
                    candidates.append(f)
        
        if candidates:
            sample_file = candidates[0]
            # Пытаемся найти точное совпадение цифр
            identifiers_digits = [re.sub(r'\D', '', x) for x in found_identifiers]
            for cand in candidates:
                cand_digits = re.sub(r'\D', '', cand)
                for ident in identifiers_digits:
                    if len(ident) >= 5 and ident in cand_digits:
                        sample_file = cand
                        break
    except: pass
    
    return sample_file, target_dir

def generate_new_name(sample_filename):
    name_without_ext, ext = os.path.splitext(sample_filename)
    date_match = re.search(r'(\d{8})', name_without_ext)
    if date_match:
        base_part = name_without_ext[:date_match.end()]
        new_name = f"{base_part}_печать{ext}"
    else:
        if '_' in name_without_ext:
            parts = name_without_ext.rsplit('_', 1)
            new_name = f"{parts[0]}_печать{ext}"
        else:
            new_name = f"{name_without_ext}_печать{ext}"
    return new_name

def process_files():
    print(f"--- STARTING SMART SORT (V5 - Deep Crawler) ---")
    print(f"Dry Run: {DRY_RUN}\n")
    
    if not os.path.exists(POPPLER_PATH):
        print(f"ERROR: {POPPLER_PATH} not found")
        return

    # ЭТАП 1: Индексация (Долгая, но тщательная)
    CASE_INDEX, UIN_INDEX = build_deep_archive_indices()
    
    report_file = "Otchet_Acts.csv"
    report_data = []
    
    if not os.path.exists(SOURCE_FOLDER):
        print("Source folder not found")
        return
        
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.lower().endswith('.pdf')]
    print(f"Found {len(files)} files.\n")
    print(f"{'FILENAME':<35} | {'MATCH TYPE':<15} | {'FOUND KEY':<20} | {'STATUS':<10}")
    print("-" * 95)

    for filename in files:
        filepath = os.path.join(SOURCE_FOLDER, filename)
        
        text = get_text_from_pdf(filepath)
        if not text:
            print(f"{filename[:35]:<35} | ERROR | --- | Read Fail")
            report_data.append([filename, "---", "Ошибка чтения", "---", "---"])
            continue
            
        cases, uins = extract_identifiers_from_text(text)
        
        target_folder = None
        match_type = "---"
        match_key = "---"
        
        # А. Поиск по УИН
        for uin in uins:
            if uin in UIN_INDEX:
                target_folder = UIN_INDEX[uin]
                match_type = "RESOLUTION (UIN)"
                match_key = uin
                break
        
        # Б. Поиск по Номеру Дела
        if not target_folder:
            for case in cases:
                if case in CASE_INDEX:
                    target_folder = CASE_INDEX[case]
                    match_type = "CASE NUMBER"
                    match_key = case
                    break
        
        # Подготовка ключа для Excel
        display_key = match_key
        if isinstance(match_key, str) and match_key.isdigit() and len(match_key) > 15:
            display_key = f'="{match_key}"'
        elif match_key == "---" and (cases or uins):
            display_key = f"Cases: {cases} UINs: {uins}"[:200]

        if not target_folder:
            print(f"{filename[:35]:<35} | NOT FOUND | --- | Skip")
            report_data.append([filename, display_key, "Не найдено в архиве", "---", "---"])
            continue

        all_keys = cases + uins
        sample_file, final_target_dir = find_sample_and_target(target_folder, all_keys)
        
        if not sample_file:
            print(f"{filename[:35]:<35} | {match_type:<15} | {match_key:<20} | NO SAMPLE")
            report_data.append([filename, display_key, "Папка есть, нет образца", "---", final_target_dir])
            continue
            
        new_filename = generate_new_name(sample_file)
        target_path = os.path.join(final_target_dir, new_filename)
        
        if not DRY_RUN:
            try:
                shutil.move(filepath, target_path)
                print(f"   >>> MOVED: {new_filename}")
            except Exception as e:
                print(f"   >>> ERROR: {e}")
        else:
            print(f"   [DRY] Match by {match_type}: {match_key}")
            print(f"   [DRY] New name: {new_filename}")

        report_data.append([filename, display_key, "Да (" + match_type + ")", new_filename, final_target_dir])

    try:
        with open(report_file, "w", encoding="utf-8-sig", newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(["Исходный файл", "Найденный ключ", "Статус", "Новое имя", "Финальная папка"])
            writer.writerows(report_data)
        print(f"\nReport saved to {report_file}")
    except: pass

if __name__ == "__main__":
    process_files()