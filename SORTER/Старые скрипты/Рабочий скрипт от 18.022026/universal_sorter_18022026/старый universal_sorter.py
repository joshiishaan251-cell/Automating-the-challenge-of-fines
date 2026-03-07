import os
import re
import shutil
import csv
import logging
import yaml
import json
import time
import subprocess
import sys
import hashlib
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- КЛАСС КОНФИГУРАЦИИ ---
class Config:
    def __init__(self, config_path):
        if not os.path.exists(config_path):
            # Создаем дефолтный конфиг, если его нет
            default_config = {
                'source_root': './downloads',
                'archive_paths': ['./archive'],
                'poppler_path': r'C:\poppler\Library\bin\pdftotext.exe',
                'dry_run': True,
                'csv_encoding': 'utf-8-sig',
                'csv_delimiter': ';',
                'cache_file': 'archive_cache.json',
                'cache_ttl_hours': 24
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(default_config, f, allow_unicode=True)
            logger.warning(f"Создан файл конфигурации по умолчанию: {config_path}. Пожалуйста, отредактируйте его.")
            self.data = default_config
        else:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.data = yaml.safe_load(f)
        
        self.source_root = self.data.get('source_root')
        self.archive_paths = self.data.get('archive_paths', [])
        self.poppler_path = self.data.get('poppler_path')
        self.dry_run = self.data.get('dry_run', True)
        self.csv_encoding = self.data.get('csv_encoding', 'utf-8-sig')
        self.csv_delimiter = self.data.get('csv_delimiter', ';')
        self.cache_file = self.data.get('cache_file', 'archive_cache.json')
        self.cache_ttl = self.data.get('cache_ttl_hours', 24)

# --- ИНДЕКСАТОР АРХИВА (С КЭШИРОВАНИЕМ) ---
class ArchiveIndexer:
    def __init__(self, config):
        self.config = config
        self.archive_paths = config.archive_paths
        self.cache_file = config.cache_file
        # Индексы: Ключ -> Путь к папке
        self.case_index = {}      # "292245-2025" -> Path
        self.uin_index = {}       # "106..." -> Path
        self.contract_index = {}  # "123-24" -> Path

    def load_or_build(self):
        # Проверяем, есть ли флаг --force или -f в команде запуска
        force_update = '--force' in sys.argv or '-f' in sys.argv
        
        if force_update:
            logger.info("Принудительное обновление индекса (--force).")
        
        # Если флага нет и кэш свежий - грузим из файла
        elif self._load_from_cache():
            logger.info("Индекс успешно загружен из кэша.")
            return

        # Иначе строим заново
        self._build_indices()
        self._save_to_cache()

    def _load_from_cache(self):
        if not os.path.exists(self.cache_file):
            return False
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Проверка возраста кэша
            timestamp = data.get('timestamp', 0)
            if time.time() - timestamp > self.config.cache_ttl * 3600:
                logger.info("Кэш устарел, запускаем пересканирование.")
                return False
            
            self.case_index = data.get('case_index', {})
            self.uin_index = data.get('uin_index', {})
            self.contract_index = data.get('contract_index', {})
            return True
        except Exception as e:
            logger.warning(f"Ошибка чтения кэша: {e}")
            return False

    def _save_to_cache(self):
        data = {
            'timestamp': time.time(),
            'case_index': self.case_index,
            'uin_index': self.uin_index,
            'contract_index': self.contract_index
        }
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Индекс сохранен в {self.cache_file}")
        except Exception as e:
            logger.error(f"Не удалось сохранить кэш: {e}")

    def _build_indices(self):
        logger.info("Запуск ПОЛНОГО сканирования архива... Это может занять время.")
        scanned_count = 0
        
        for root_path in self.archive_paths:
            if not os.path.exists(root_path):
                logger.warning(f"Путь архива не найден: {root_path}")
                continue
                
            for current_root, dirs, files in os.walk(root_path):
                scanned_count += 1
                if scanned_count % 100 == 0:
                    sys.stdout.write(f"\r   Просканировано папок: {scanned_count}...")
                    sys.stdout.flush()

                # 1. Индексация по имени ПАПКИ
                folder_name = os.path.basename(current_root)
                self._index_folder_name(folder_name, current_root)

                # 2. Индексация по именам ФАЙЛОВ (Якоря)
                for file in files:
                    if file.lower().endswith('.pdf'):
                        self._index_file_name(file, current_root)
        
        print(f"\nСканирование завершено. Найдено дел: {len(self.case_index)}, УИН: {len(self.uin_index)}, Договоров: {len(self.contract_index)}")

    def _index_folder_name(self, folder_name, path):
        # Номер дела (А40-...)
        matches = re.findall(r'(?<!\d)(\d{5,7})\D{0,5}(202\d|2\d)(?!\d)', folder_name)
        for m in matches:
            key = f"{m[0]}-{self._normalize_year(m[1])}"
            if key not in self.case_index: self.case_index[key] = path

        # Номер договора (123-24)
        match_contract = re.search(r'(\d{2,6}[-\/]\d{2,4})', folder_name)
        if match_contract:
            key = match_contract.group(1)
            if key not in self.contract_index: self.contract_index[key] = path

    def _index_file_name(self, filename, path):
        # УИН (только цифры)
        name_no_ext = os.path.splitext(filename)[0]
        clean_name = re.sub(r'\s+', '', name_no_ext)
        if re.fullmatch(r'\d{20,29}', clean_name):
            self.uin_index[clean_name] = path

    def _normalize_year(self, year_str):
        return "20" + year_str if len(year_str) == 2 else year_str

    def find_path(self, key, key_type="case"):
        if not key: return None
        if key_type == "case": return self.case_index.get(key)
        if key_type == "uin": return self.uin_index.get(key)
        if key_type == "contract":
            if key in self.contract_index: return self.contract_index[key]
            # Частичное совпадение для договоров
            for k, path in self.contract_index.items():
                if key in k or k in key: return path
        return None

# --- БАЗОВЫЙ ПРОЦЕССОР ---
class DocumentProcessor(ABC):
    def __init__(self, config, indexer):
        self.config = config
        self.indexer = indexer
        # Загружаем путь к Tesseract из конфига
        self.tesseract_path = getattr(config, 'tesseract_path', config.data.get('tesseract_path'))

    def run_poppler(self, pdf_path):
        if not self.config.poppler_path or not os.path.exists(self.config.poppler_path):
            return None
        try:
            cmd = [self.config.poppler_path, '-layout', '-enc', 'UTF-8', pdf_path, '-']
            # ТАЙМАУТ 30 СЕКУНД
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                   text=True, encoding='utf-8', errors='replace', timeout=30)
            return result.stdout if result.returncode == 0 else None
        except subprocess.TimeoutExpired:
            logger.error(f"Poppler timeout (30s) on: {os.path.basename(pdf_path)}")
            return None
        except Exception:
            return None

    def run_ocr(self, pdf_path):
        """Третий уровень: Распознавание текста с картинки (OCR)"""
        if not self.tesseract_path or not os.path.exists(self.tesseract_path):
            return ""
        try:
            # Указываем путь к Tesseract
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path
            
            # Для pdf2image нужен путь к папке bin попплера
            poppler_bin_dir = os.path.dirname(self.config.poppler_path)
            
            # Превращаем первую страницу PDF в картинку
            images = convert_from_path(pdf_path, poppler_path=poppler_bin_dir, first_page=1, last_page=1)
            
            if not images:
                return ""
                
            # Распознаем текст на РУССКОМ языке
            ocr_text = pytesseract.image_to_string(images[0], lang='rus')
            return ocr_text
        except Exception as e:
            logger.error(f"Ошибка OCR на файле {os.path.basename(pdf_path)}: {e}")
            return ""

    def extract_text(self, pdf_path):
        text = ""
        # 1. УРОВЕНЬ 1: Быстрое чтение цифровых PDF (pdfplumber)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if pdf.pages:
                    text = pdf.pages[0].extract_text() or ""
        except Exception:
            pass
        
        # 2. УРОВЕНЬ 2: Сложное форматирование (Poppler)
        if not text or len(text.strip()) < 50:
             poppler_text = self.run_poppler(pdf_path)
             if poppler_text: text = poppler_text
             
        # 3. УРОВЕНЬ 3: Слепые сканы и фото (Tesseract OCR)
        if not text or len(text.strip()) < 50:
             logger.info(f"Запуск OCR для 'слепого' файла: {os.path.basename(pdf_path)}")
             ocr_text = self.run_ocr(pdf_path)
             if ocr_text: text = ocr_text
             
        return text

    def get_file_hash(self, file_path):
        """Возвращает MD5 хэш файла для сравнения содержимого"""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()

    def move_file(self, src, dst_folder, new_name):
        if not self.config.dry_run:
            try:
                if not os.path.exists(dst_folder):
                    os.makedirs(dst_folder, exist_ok=True)
                
                final_path = os.path.join(dst_folder, new_name)
                
                # ЛОГИКА ДУБЛИКАТОВ
                if os.path.exists(final_path):
                    # 1. Сравниваем хэши
                    src_hash = self.get_file_hash(src)
                    dst_hash = self.get_file_hash(final_path)
                    
                    if src_hash == dst_hash:
                        # Файлы идентичны -> удаляем исходник
                        try:
                            os.remove(src)
                            return True, f"{new_name} (ДУБЛЬ УДАЛЕН)"
                        except OSError:
                            return False, "Ошибка удаления дубля"
                    
                    # 2. Если файлы разные -> переименовываем (_1, _2...)
                    base, ext = os.path.splitext(new_name)
                    counter = 1
                    while os.path.exists(final_path):
                        final_path = os.path.join(dst_folder, f"{base}_{counter}{ext}")
                        counter += 1

                shutil.move(src, final_path)
                return True, os.path.basename(final_path)
            except Exception as e:
                return False, str(e)
        else:
            return True, new_name

    def find_subfolder(self, base_folder, partial_name):
        try:
            for item in os.listdir(base_folder):
                if os.path.isdir(os.path.join(base_folder, item)):
                    if partial_name.lower() in item.lower():
                        return os.path.join(base_folder, item)
        except: pass
        return base_folder

    @abstractmethod
    def process(self, pdf_path, text):
        pass

# --- ПРОЦЕССОР АКТОВ (КОПИРУЕТ ИМЯ ЯКОРЯ) ---
class ActProcessor(DocumentProcessor):
    def process(self, pdf_path, text):
        clean_text = text.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
        
        # 1. Поиск УИН (для поиска папки)
        found_uins = []
        potential_uins = re.findall(r'(106[\d\s\-]{17,35})', clean_text)
        for p_uin in potential_uins:
            digits = re.sub(r'\D', '', p_uin)
            if len(digits) >= 20: found_uins.append(digits)

        # 2. Поиск Номеров Дел (для поиска папки)
        found_cases = []
        # Контекстный поиск (Дело №...)
        keyword_matches = re.finditer(r'(?:Дело|N|№|Решение)', clean_text, re.IGNORECASE)
        for match in keyword_matches:
            snippet = clean_text[match.end():match.end()+50]
            table = str.maketrans("ЗОБЧАSsg", "30644559") 
            snippet_fixed = snippet.translate(table)
            matches = re.findall(r'(?<!\d)(\d{5,7})\D{0,5}(202\d|2\d)(?!\d)', snippet_fixed)
            for m in matches:
                found_cases.append(f"{m[0]}-{self._normalize_year(m[1])}")

        # Прямой формат (A40...)
        std_matches = re.findall(r'40[\s\-\/\\]+(\d{5,7})[\s\-\/\\]+(\d{2,4})', clean_text)
        for m in std_matches:
            found_cases.append(f"{m[0]}-{self._normalize_year(m[1])}")

        found_cases = list(set(found_cases))
        found_uins = list(set(found_uins))

        # 3. Поиск в индексе (Куда класть?)
        target_path = None
        match_key = "---"
        match_type = "---"

        # Сначала ищем по УИН
        for uin in found_uins:
            path = self.indexer.find_path(uin, "uin")
            if path:
                target_path, match_key, match_type = path, uin, "UIN"
                break
        
        # Если не нашли, ищем по номеру дела
        if not target_path:
            for case in found_cases:
                path = self.indexer.find_path(case, "case")
                if path:
                    target_path, match_key, match_type = path, case, "Case"
                    break

        if not target_path:
            all_keys = found_cases + found_uins
            return {"status": "Not Found", "match_key": all_keys if all_keys else "---"}

        # 4. Определяем конечную папку
        final_target_dir = target_path
        sub_dir = self.find_subfolder(target_path, "3 Заявление")
        if sub_dir: final_target_dir = sub_dir
        
        # --- ЛОГИКА ИМЕНОВАНИЯ: БЕРЕМ ОТ "ЯКОРЯ" ---
        new_name = None
        
        try:
            # Ищем файл в папке, который начинается на "! Взыскано"
            # Это и есть наш "Якорь" (образец)
            files_in_folder = os.listdir(final_target_dir)
            for file in files_in_folder:
                if file.startswith("! Взыскано") and file.endswith(".pdf"):
                    # Мы нашли файл-образец! 
                    # Например: "! Взыскано A40-314475-2025_20260127.pdf"
                    
                    # Проверяем, чтобы это не был уже файл с печатью (чтобы не плодить _печать_печать)
                    if "_печать" not in file:
                        anchor_name = os.path.splitext(file)[0]
                        new_name = f"{anchor_name}_печать.pdf"
                        break
        except Exception as e:
            logger.error(f"Ошибка поиска якоря: {e}")

        # Если якорь ("! Взыскано...") не найден, формируем запасное имя
        if not new_name:
            current_date = datetime.now().strftime("%Y%m%d")
            # Берем номер дела из поиска или из ключа
            case_part = f"A40-{match_key}" if "A40" not in str(match_key) else match_key
            if found_cases: case_part = f"A40-{found_cases[0]}"
            
            new_name = f"! Взыскано {case_part}_{current_date}_печать.pdf"

        # 5. Перемещение
        success, final_name = self.move_file(pdf_path, final_target_dir, new_name)
        return {"status": "Success", "match_type": match_type, "match_key": match_key, 
                "target_path": final_target_dir, "new_name": final_name}
    
    def _normalize_year(self, year_str):
        return "20" + year_str if len(year_str) == 2 else year_str

# --- ПРОЦЕССОР ЧЕКОВ И ПЛАТЕЖЕК (ГИБРИДНЫЙ) ---
class CheckProcessor(DocumentProcessor):
    def process(self, pdf_path, text):
        # Чистим текст в одну строку
        clean_text = text.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
        uin = None
        date_str = None
        
        # Определяем: это Платежное поручение или Чек?
        is_payment_order = "ПЛАТЕЖНОЕ ПОРУЧЕНИЕ" in clean_text.upper()
        
        if is_payment_order:
            # --- ЛОГИКА ДЛЯ ПЛАТЕЖЕК (Ручной ввод, ошибки, слипшиеся слова) ---
            # Ищем варианты слова "постановление" + (возможно мусор) + (возможно пробел) + Длинный номер
            # Регулярка:
            # (?:пост|постановл) - начало слова
            # [а-я\.]* - любые окончания слова (ению, я, ие...)
            # [:\s№]* - возможные разделители (пробел, двоеточие, знак номера) или ИХ ОТСУТСТВИЕ
            # (\d{20,29}) - сам номер
            
            patterns = [
                # 1. Поиск по слову "Постановление" (ловит "постановлению1067..." и "пост. 1067...")
                r'(?:пост|постановл|штраф)[а-я\.]*[:\s№]*(\d{20,29})',
                # 2. Поиск по УИН (на всякий случай, если бухгалтер написал грамотно)
                r'УИН[:\s№]*(\d{20,29})'
            ]
            
            candidates = []
            for pat in patterns:
                found = re.findall(pat, clean_text, re.IGNORECASE)
                candidates.extend(found)
            
            # Фильтруем (на всякий случай убираем счета 408..., если вдруг попали)
            valid_candidates = [c for c in candidates if not c.startswith(("408", "407", "301"))]
            
            if valid_candidates:
                # Приоритет номерам на 106, 188, 322
                prio = next((x for x in valid_candidates if x.startswith(("106", "188", "322"))), None)
                uin = prio if prio else valid_candidates[0]

        else:
            # --- ЛОГИКА ДЛЯ ЧЕКОВ (Строгая, как раньше) ---
            # Ищем только после ключевых слов
            m = re.search(r'(?:УИН|Идентификатор|Постановление)[:\.\s]*(\d{20,29})', clean_text, re.IGNORECASE)
            if m: uin = m.group(1)

        # 2. Поиск Даты (общий для всех)
        m_date = re.search(r'(\d{2}[\.\/]\d{2}[\.\/]\d{4})', clean_text)
        if m_date: date_str = m_date.group(1).replace('/', '.')
        
        # --- ФИНАЛ ---
        if not uin: return {"status": "Not Found (No UIN)", "match_key": "---"}

        # Поиск в индексе
        target_path = self.indexer.find_path(uin, "uin")
        if not target_path: return {"status": "Not Found (Archive)", "match_key": uin}

        # Выбор папки
        final_target_dir = target_path
        sub_dir = self.find_subfolder(target_path, "3 Заявление")
        if sub_dir: final_target_dir = sub_dir
            
        # Формирование имени
        safe_date = date_str.replace('.', '-') if date_str else "без_даты"
        ext = os.path.splitext(pdf_path)[1]
        new_name = f"Чек_{safe_date}_{uin}{ext}"
        
        success, final_name = self.move_file(pdf_path, final_target_dir, new_name)
        return {"status": "Success", "match_type": "UIN", "match_key": uin, 
                "target_path": final_target_dir, "new_name": final_name}

# --- ПРОЦЕССОР ПЛАТЕЖЕЙ/ДОГОВОРОВ ---
class PaymentProcessor(DocumentProcessor):
    def process(self, pdf_path, text):
        clean_text = text.replace('\n', ' ').replace('\t', ' ')
        contract_num = None
        
        match = re.search(r'[№N]\s*([А-Яа-яA-Za-z0-9\-\/]{3,20})', clean_text)
        if match: contract_num = match.group(1).strip("., ")
        
        if not contract_num: return {"status": "Not Found (No Num)", "match_key": "---"}

        target_path = self.indexer.find_path(contract_num, "contract")
        if not target_path: return {"status": "Not Found (Archive)", "match_key": contract_num}

        original_name = os.path.basename(pdf_path)
        success, final_name = self.move_file(pdf_path, target_path, original_name)
        
        return {"status": "Success", "match_type": "Contract", "match_key": contract_num, 
                "target_path": target_path, "new_name": final_name}

# --- ГЛАВНЫЙ ОРКЕСТРАТОР ---
def main():
    print(f"--- Universal Sorter v3.0 (Final) ---\n")
    try:
        config = Config('config.yaml')
    except Exception as e:
        print(f"Ошибка конфига: {e}"); return

    # 1. Загрузка индексов
    indexer = ArchiveIndexer(config)
    indexer.load_or_build()

    # 2. Инициализация процессоров
    processors = {
        'act': ActProcessor(config, indexer),
        'check': CheckProcessor(config, indexer),
        'payment': PaymentProcessor(config, indexer)
    }

    report_data = []
    
    if not os.path.exists(config.source_root):
        print("Папка с загрузками не найдена!"); return

    print(f"\nСканирование новых файлов в: {config.source_root}")
    print(f"Режим: {'ТЕСТ (DRY RUN)' if config.dry_run else 'БОЕВОЙ'}")
    print(f"{'ФАЙЛ':<30} | {'ТИП':<10} | {'СТАТУС':<15} | {'КЛЮЧ'}")
    print("-" * 90)

    for root, dirs, files in os.walk(config.source_root):
        for filename in files:
            if not filename.lower().endswith('.pdf'): continue
            
            filepath = os.path.join(root, filename)
            
            # Извлекаем текст
            text = processors['act'].extract_text(filepath)
            text_lower = text.lower()
            
            # Классификация
            if "платежное поручение" in text_lower or "чек по операции" in text_lower or "сбербанк" in text_lower:
                p_type, proc = 'Check', processors['check']
            elif "решение" in text_lower or "постановление" in text_lower or "именем российской федерации" in text_lower:
                p_type, proc = 'Act', processors['act']
            elif "договор" in text_lower or "счет на оплату" in text_lower:
                p_type, proc = 'Payment', processors['payment']
            else:
                p_type, proc = 'Act (Default)', processors['act']

            # Обработка
            try:
                res = proc.process(filepath, text)
            except Exception as e:
                res = {"status": "Error", "match_key": str(e)}

            # Retry Logic (если не нашли как Акт, пробуем как Платеж)
            if "Not Found" in res['status'] and p_type != 'Payment' and p_type != 'Check':
                res_pay = processors['payment'].process(filepath, text)
                if res_pay['status'] == "Success":
                    res, p_type = res_pay, 'Payment (Retry)'

            # --- ФОРМАТИРОВАНИЕ ДЛЯ ОТЧЕТА ---
            raw_key = res.get('match_key', '---')
            
            # Убираем списки Python
            if isinstance(raw_key, list):
                key_str = ", ".join(str(k) for k in raw_key)
            else:
                key_str = str(raw_key)
            
            key_str = key_str.replace("['", "").replace("']", "").replace("'", "")
            
            # Хак для Excel (чтобы длинные цифры не ломались)
            csv_key_format = key_str
            if key_str.isdigit() and len(key_str) > 15:
                csv_key_format = f'="{key_str}"'

            # Вывод в консоль (урезанный)
            print(f"{filename[:30]:<30} | {p_type:<10} | {res.get('status', 'Unknown'):<15} | {key_str[:25]}")
            
            report_data.append([
                filename, p_type, res.get('status', 'Unknown'), 
                csv_key_format,
                res.get('new_name', ''), res.get('target_path', '')
            ])

   # Сохранение отчета с уникальным именем (Дата_Время_Секунды)
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    csv_file = f'universal_report_{current_time}.csv'
    
    try:
        with open(csv_file, 'w', encoding=config.csv_encoding, newline='') as f:
            w = csv.writer(f, delimiter=config.csv_delimiter)
            w.writerow(["Файл", "Тип", "Статус", "Ключ", "Новое Имя", "Путь"])
            w.writerows(report_data)
        print(f"\nОтчет сохранен: {csv_file}")
    except Exception as e:
        print(f"\nОшибка при сохранении отчета: {e}")

if __name__ == "__main__":
    main()