import os
import re
import shutil
import csv
import pdfplumber
from datetime import datetime

# --- 1. НАСТРОЙКИ (CONFIGURATION) ---

# Корневая папка, откуда забираем файлы (Скрипт просканирует все подпапки внутри)
SOURCE_ROOT = r"C:\Users\Logik\Downloads\платежи штрафы 21112024"

# Где ищем папки договоров/дел (Архивы)
ARCHIVE_PATHS = [
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА\1 ИЛ",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив Штрафы ИП КОА",
    r"C:\Users\Logik\Documents\ИП Коротаев ОА\Архив ОТКАЗЫ Штрафы\А Повтор"
]

# True = Тестовый режим (только отчет), False = Реальное перемещение
DRY_RUN = True

# Файл отчета
REPORT_FILE = "Otchet_Payments.csv"

# --- 2. ЛОГИКА (FUNCTIONS) ---

def extract_contract_number(pdf_path):
    """
    Ищет номер договора (или дела) в тексте PDF.
    Паттерн: № 12345/20... или № А40-...
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Читаем первую страницу (обычно номер там)
            if len(pdf.pages) > 0:
                text = pdf.pages[0].extract_text()
                if not text: return None
                
                # Очистка текста
                clean_text = text.replace('\n', ' ').replace('\t', ' ')
                
                # 1. Ищем номер договора/дела
                # Ищем слово "№" или "N" и следующие за ним цифры/буквы
                # Пример: № 77-12/2024 или № А40-12345
                pattern = r'[№N]\s*([А-Яа-яA-Za-z0-9\-\/]{3,20})'
                match = re.search(pattern, clean_text)
                
                if match:
                    # Убираем лишние символы в конце, если захватили точку или запятую
                    return match.group(1).strip("., ")
                    
    except Exception as e:
        print(f"[WARN] Ошибка чтения {os.path.basename(pdf_path)}: {e}")
        return None
    return None

def build_archive_index():
    """
    Сканирует архив (принцип Паука) и запоминает, где какая папка лежит.
    Возвращает словарь: { "НОМЕР_ДОГОВОРА": "ПУТЬ_К_ПАПКЕ" }
    """
    print("--- ИНДЕКСАЦИЯ АРХИВА (Deep Scan) ---")
    index = {}
    count = 0
    
    for root_path in ARCHIVE_PATHS:
        if not os.path.exists(root_path): continue
        
        # Рекурсивный обход всех папок архива
        for current_root, dirs, files in os.walk(root_path):
            folder_name = os.path.basename(current_root)
            
            # Попытка извлечь номер из названия папки
            # Ищем что-то похожее на номер (цифры, тире, год)
            # Пример папки: "Договор № 123-24 Иванов" -> Ключ "123-24"
            
            # Вариант А: Номер дела А40-...
            match_a40 = re.search(r'(A40-\d{3,}-\d{2,4})', folder_name.replace('А', 'A').upper())
            if match_a40:
                key = match_a40.group(1)
                index[key] = current_root
                continue

            # Вариант Б: Просто номер договора (цифры-цифры)
            # Ищем группу цифр, возможно разделенных тире
            match_contract = re.search(r'(\d{2,6}[-\/]\d{2,4})', folder_name)
            if match_contract:
                key = match_contract.group(1)
                if key not in index:
                    index[key] = current_root
                    
            count += 1
            if count % 500 == 0:
                print(f"   Просмотрено папок: {count}...", end='\r')
                
    print(f"\n   Проиндексировано папок-целей: {len(index)}")
    return index

def find_target_in_index(archive_index, search_key):
    """
    Ищет ключ в индексе.
    """
    if not search_key: return None
    
    # 1. Прямое совпадение
    if search_key in archive_index:
        return archive_index[search_key]
        
    # 2. Частичное совпадение (если в PDF номер "123-24", а папка "123-24/А")
    for key, path in archive_index.items():
        if search_key in key or key in search_key:
            return path
            
    return None

def process_files():
    print(f"--- ЗАПУСК СОРТИРОВКИ ПЛАТЕЖЕЙ (PAUK VERSION) ---")
    print(f"Источник: {SOURCE_ROOT}")
    print(f"Dry Run: {DRY_RUN}\n")

    # 1. Строим карту архива
    archive_index = build_archive_index()
    
    results = []
    
    # 2. Сканируем источник (Паук)
    if not os.path.exists(SOURCE_ROOT):
        print(f"ОШИБКА: Папка источника не найдена: {SOURCE_ROOT}")
        return

    files_found = 0
    
    # os.walk заходит во все подпапки источника
    for current_root, dirs, files in os.walk(SOURCE_ROOT):
        for filename in files:
            if not filename.lower().endswith('.pdf'):
                continue
                
            files_found += 1
            filepath = os.path.join(current_root, filename)
            
            # А. Ищем номер в PDF
            contract_num = extract_contract_number(filepath)
            
            status = "---"
            target_folder = "---"
            
            if contract_num:
                # Б. Ищем папку в архиве
                target_folder = find_target_in_index(archive_index, contract_num)
                
                if target_folder:
                    status = "Найдено"
                    # Перемещение
                    if not DRY_RUN:
                        try:
                            # Проверка на дубликаты имени
                            dst_path = os.path.join(target_folder, filename)
                            if os.path.exists(dst_path):
                                name, ext = os.path.splitext(filename)
                                dst_path = os.path.join(target_folder, f"{name}_copy{ext}")
                                
                            shutil.move(filepath, dst_path)
                            status = "Перемещено"
                            print(f"   [OK] {filename} -> {target_folder}")
                        except Exception as e:
                            status = f"Ошибка: {e}"
                            print(f"   [ERR] {e}")
                    else:
                        status = "Тест (Найдено)"
                        print(f"   [DRY] {filename} -> {target_folder}")
                else:
                    status = "Нет папки в архиве"
                    print(f"   [---] {filename}: Номер {contract_num} не найден в архиве")
            else:
                status = "Номер не найден в PDF"
                # print(f"   [---] {filename}: Пусто")

            # Запись в отчет
            results.append([filename, contract_num if contract_num else "---", status, target_folder])

    print(f"\nОбработано файлов: {files_found}")

    # 3. Сохраняем отчет
    try:
        with open(REPORT_FILE, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Имя файла", "Найденный номер", "Статус", "Папка назначения"])
            writer.writerows(results)
        print(f"Отчет сохранен: {REPORT_FILE}")
    except Exception as e:
        print(f"Ошибка сохранения отчета: {e}")

if __name__ == "__main__":
    process_files()