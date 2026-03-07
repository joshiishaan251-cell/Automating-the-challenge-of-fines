import os
import re
import shutil
import csv
import pdfplumber
from datetime import datetime

# --- 1. НАСТРОЙКИ (CONFIGURATION) ---

# Корневая папка с новыми чеками/платежками
SOURCE_ROOT = r"C:\Users\Logik\Downloads\платежи штрафы 21112024"

# Где ищем дела (Архивы) - скрипт просканирует их глубоко
ARCHIVE_PATHS = [
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА\1 ИЛ",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив ОТКАЗЫ Штрафы\А Повтор"
]

# True = Тестовый режим, False = Боевой режим
DRY_RUN = True

# Файл отчета
REPORT_FILE = "Otchet_Cheki.csv"

# --- 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def extract_uin_and_date(pdf_path):
    """
    Умный поиск УИН (номера постановления) и даты.
    Различает Чеки и Платежные поручения.
    """
    uin = None
    date_str = None
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages: return None, None
            
            text = pdf.pages[0].extract_text()
            if not text: return None, None
            
            # Очистка текста
            clean_text = text.replace('\n', ' ').replace('\t', ' ')
            
            # --- 1. ОПРЕДЕЛЕНИЕ ТИПА ДОКУМЕНТА ---
            # Ищем маркеры платежного поручения
            is_payment_order = bool(re.search(r'ПЛАТЕЖНОЕ\s+ПОРУЧЕНИЕ', clean_text, re.IGNORECASE))
            
            # --- 2. ПОИСК УИН (Контекстный) ---
            found_context_uin = None
            
            if is_payment_order:
                # ЛОГИКА ДЛЯ ПЛАТЕЖЕК: Ищем в назначении платежа
                # Ключевые слова: "штрафа", "постановлению", "протоколу"
                # Регулярка ищет слово, потом любой мусор (или ничего), потом 20-29 цифр
                # Это ловит и "постановлению 106..." и "постановлению106..." (слитно)
                patterns_pp = [
                    r'(?:штраф|постановлени|протокол)[а-яА-Яa-zA-Z0-9\s\.\,\-\/\(\)]*?(\d{20,29})',
                    r'УИН[а-яА-Яa-zA-Z0-9\s\.\,\-\/\(\):]*?(\d{20,29})'
                ]
                
                for pat in patterns_pp:
                    match = re.search(pat, clean_text, re.IGNORECASE)
                    if match:
                        cand = match.group(1)
                        # Проверка, что это не счет (на всякий случай)
                        if not cand.startswith(("408", "407", "301", "302", "031", "032")):
                            found_context_uin = cand
                            break
            else:
                # ЛОГИКА ДЛЯ ЧЕКОВ (Сбер и др.): Ищем поле УИН
                match = re.search(r'(?:УИН|Идентификатор|Постановление)[:\.\s]*(\d{20,29})', clean_text, re.IGNORECASE)
                if match:
                    found_context_uin = match.group(1)

            # Принимаем решение
            if found_context_uin:
                uin = found_context_uin
            else:
                # ПЛАН Б: Если контекстный поиск не сработал, ищем ЛЮБОЕ подходящее длинное число
                # (как раньше, но с жестким фильтром счетов)
                all_long_numbers = re.findall(r'(\d{20,29})', clean_text)
                candidates = []
                for num in all_long_numbers:
                    # Жесткий фильтр банковских счетов
                    if num.startswith(("408", "407", "301", "302", "031", "032")):
                        continue
                    candidates.append(num)
                
                if candidates:
                    # Приоритет номерам на 106 (Ространснадзор) и 188 (ГИБДД)
                    priority_match = next((x for x in candidates if x.startswith(("106", "188"))), None)
                    uin = priority_match if priority_match else candidates[0]

            # --- 3. ПОИСК ДАТЫ ---
            match_date = re.search(r'(\d{2}[\.\/]\d{2}[\.\/]\d{4})', clean_text)
            if match_date:
                date_str = match_date.group(1).replace('/', '.')
            else:
                match_text_date = re.search(r'(\d{1,2}\s+[а-яА-Я]+\s+\d{4})', clean_text)
                if match_text_date:
                    date_str = match_text_date.group(1)

    except Exception as e:
        print(f"[WARN] Ошибка чтения {os.path.basename(pdf_path)}: {e}")
        return None, None
        
    return uin, date_str

def build_deep_archive_index():
    print("--- ИНДЕКСАЦИЯ АРХИВА (Deep Scan) ---")
    index = {}
    scanned_folders = 0
    
    for root_path in ARCHIVE_PATHS:
        if not os.path.exists(root_path): continue
        
        for current_root, dirs, files in os.walk(root_path):
            scanned_folders += 1
            if scanned_folders % 500 == 0:
                print(f"   Просмотрено папок: {scanned_folders}...", end='\r')
                
            for file in files:
                if file.lower().endswith('.pdf'):
                    name_no_ext = os.path.splitext(file)[0]
                    clean_name = re.sub(r'\s+', '', name_no_ext)
                    # Якорь - это файл, имя которого состоит ТОЛЬКО из цифр
                    if re.fullmatch(r'\d{20,29}', clean_name):
                        uin_key = clean_name
                        index[uin_key] = current_root
                        
    print(f"\n   Найдено дел (по файлам-якорям): {len(index)}")
    print("-" * 60)
    return index

def find_target_folder_logic(base_folder):
    try:
        items = os.listdir(base_folder)
        for item in items:
            full_path = os.path.join(base_folder, item)
            if os.path.isdir(full_path):
                if item.strip().startswith("3 Заявление в МТУ"):
                    return full_path
    except: pass
    return base_folder

def generate_check_name(original_name, date_str, uin):
    safe_date = date_str if date_str else "без_даты"
    safe_date = safe_date.replace('.', '-').replace(' ', '_')
    ext = os.path.splitext(original_name)[1]
    new_name = f"Чек_{safe_date}_{uin}{ext}"
    return new_name

def cleanup_archive(archive_index, report_data):
    print("\n--- ЗАПУСК РЕВИЗОРА (CLEANUP) ---")
    for uin, folder_path in archive_index.items():
        target_subfolder = None
        try:
            items = os.listdir(folder_path)
            for item in items:
                if os.path.isdir(os.path.join(folder_path, item)) and item.startswith("3 Заявление в МТУ"):
                    target_subfolder = os.path.join(folder_path, item)
                    break
        except: continue
        
        if not target_subfolder: continue
            
        try:
            files_in_root = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
            for f in files_in_root:
                name_no_ext = os.path.splitext(f)[0]
                clean_name = re.sub(r'\s+', '', name_no_ext)
                if re.fullmatch(r'\d{20,29}', clean_name): continue 
                if f.startswith("! Взыскано"): continue 

                src_path = os.path.join(folder_path, f)
                dst_path = os.path.join(target_subfolder, f)
                
                if not DRY_RUN:
                    try:
                        shutil.move(src_path, dst_path)
                        print(f"   [CLEANUP] Перемещен: {f}")
                        report_data.append([f, f'="{uin}"', "---", "Досортировка (Архив)", f, target_subfolder])
                    except: pass
        except: pass

def verify_archive(archive_index, report_data):
    print("\n--- ФИНАЛЬНАЯ ПРОВЕРКА (VERIFICATION) ---")
    count_ok = 0
    count_bad = 0
    
    for uin, folder_path in archive_index.items():
        target_dir = find_target_folder_logic(folder_path)
        has_subfolder = (target_dir != folder_path)
        if not has_subfolder: continue
            
        check_found = False
        try:
            files = os.listdir(target_dir)
            for f in files:
                if f.lower().endswith('.pdf') and not f.startswith("! Взыскано"):
                    check_found = True
                    break
        except: pass
        
        if check_found:
            count_ok += 1
        else:
            count_bad += 1
            report_data.append(["---", f'="{uin}"', "---", "ВНИМАНИЕ: Нет чека в заявлении", "---", target_dir])
            print(f"   [ALARM] Нет чека в: {target_dir}")

    print(f"   Проверено дел с заявлениями: {count_ok + count_bad}")
    print(f"   Чеки на месте: {count_ok}, Пусто: {count_bad}")

# --- 3. ОСНОВНАЯ ЛОГИКА ---

def process_files():
    print(f"--- STARTING CHECKS SORT (PAYMENT ORDER FIX) ---")
    print(f"Dry Run: {DRY_RUN}\n")

    archive_index = build_deep_archive_index()
    report_data = []
    
    if not os.path.exists(SOURCE_ROOT):
        print(f"ОШИБКА: Не найдена папка: {SOURCE_ROOT}")
        return

    files_processed = 0
    
    for current_root, dirs, files in os.walk(SOURCE_ROOT):
        for filename in files:
            if not filename.lower().endswith('.pdf'): continue
                
            files_processed += 1
            filepath = os.path.join(current_root, filename)
            
            uin, date_str = extract_uin_and_date(filepath)
            uin_csv = f'="{uin}"' if uin else "---"
            
            if not uin:
                print(f"{filename[:35]:<35} | NO UIN FOUND | ---")
                report_data.append([filename, "---", "---", "УИН не найден", "---", "---"])
                continue
            
            if uin in archive_index:
                case_folder = archive_index[uin]
                final_target_dir = find_target_folder_logic(case_folder)
                new_filename = generate_check_name(filename, date_str, uin)
                target_path = os.path.join(final_target_dir, new_filename)
                
                status = "Найдено"
                if not DRY_RUN:
                    try:
                        if os.path.exists(target_path):
                            name, ext = os.path.splitext(new_filename)
                            new_filename = f"{name}_copy{ext}"
                            target_path = os.path.join(final_target_dir, new_filename)
                        shutil.move(filepath, target_path)
                        status = "Перемещено"
                        print(f"   [OK] {filename} -> {final_target_dir}")
                    except Exception as e:
                        status = f"Ошибка: {e}"
                        print(f"   [ERR] {e}")
                else:
                    print(f"   [DRY] Match: {uin}")
                
                report_data.append([filename, uin_csv, date_str, status, new_filename, final_target_dir])
            else:
                print(f"{filename[:35]:<35} | {uin:<20} | NOT IN ARCHIVE")
                report_data.append([filename, uin_csv, date_str, "Нет в архиве", "---", "---"])

    print(f"\nОбработано файлов: {files_processed}")

    if not DRY_RUN:
        cleanup_archive(archive_index, report_data)
    
    verify_archive(archive_index, report_data)

    try:
        with open(REPORT_FILE, "w", encoding="utf-8-sig", newline='') as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(["Исходный файл", "УИН", "Дата", "Статус", "Новое имя", "Финальная папка"])
            writer.writerows(report_data)
        print(f"\nОтчет сохранен: {REPORT_FILE}")
    except: pass

if __name__ == "__main__":
    process_files()