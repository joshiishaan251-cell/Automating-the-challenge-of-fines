import os
import asyncio
import urllib.parse
import logging
import warnings
import re
from pathlib import Path
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from playwright.async_api import async_playwright
    import google.generativeai as genai
except ImportError:
    print("Ошибка: pip install playwright google-generativeai python-dotenv")
    exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# Настройки ресурсов согласно AGENTS.md
def find_resources():
    user_home = Path.home()
    local_app = Path(os.environ.get('LOCALAPPDATA', ''))
    exes = [
        local_app / r"Chromium\Application\chrome.exe",
        user_home / r"AppData\Local\Chromium\Application\chrome.exe",
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ]
    data_dirs = [
        local_app / r"Chromium\User Data",
        user_home / r"AppData\Local\Chromium\User Data",
    ]
    return next((p for p in exes if p.exists()), None), next((p for p in data_dirs if p.exists()), None)

TEXT_DUMP = Path("case_text_dump.txt")

async def get_refined_query(text: str) -> str:
    """Выделяет суть спора без лишнего шума."""
    log.info("🤖 ИИ анализирует суть документа...")
    genai.configure(api_key=API_KEY)
    # Используем полный путь к модели для стабильности
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    prompt = f"Выдели 2-4 ключевых слова для поиска практики (без дат и судов): {text[:2500]}"
    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text.strip().replace('"', '')
    except Exception:
        return "взыскание задолженности по договору перевозки"

async def run_automation():
    exe_path, data_path = find_resources()
    if not exe_path: return

    case_text = TEXT_DUMP.read_text(encoding="utf-8") if TEXT_DUMP.exists() else "перевозка"
    keywords = await get_refined_query(case_text)
    log.info(f"✅ КЛЮЧЕВЫЕ СЛОВА: {keywords}")

    async with async_playwright() as p:
        log.info(f"🚀 Запуск {exe_path.name} (Окно на весь экран)...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(data_path) if data_path else "",
            executable_path=str(exe_path),
            headless=False,
            no_viewport=True, # Окно на весь экран
            args=["--no-first-run", "--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"]
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        log.info("Переход в раздел Судебной практики 1jur.ru...")
        await page.goto("https://1jur.ru/#/lawpractice/", wait_until="networkidle")

        try:
            # 1. Активация панели "ПО РЕКВИЗИТАМ"
            log.info("Активация расширенного поиска...")
            # Поиск всех кнопок для диагностики
            btns = page.get_by_text("ПО РЕКВИЗИТАМ").filter(visible=True)
            log.info(f"Найдено кнопок 'ПО РЕКВИЗИТАМ': {await btns.count()}")
            
            btn_requisites = btns.first
            await btn_requisites.scroll_into_view_if_needed()
            await btn_requisites.hover()
            await btn_requisites.click(force=True)
            
            # Ждем появления ХОТЯ БЫ ОДНОГО визуального якоря
            log.info("Ожидание появления любого признака открытия панели...")
            anchor_found = False
            for attempt in range(3):
                try:
                    # Создаем задачи для ожидания различных элементов
                    tasks = [
                        page.get_by_text("только точную фразу").filter(visible=True).first.wait_for(state="visible"),
                        page.get_by_text("Вид").filter(visible=True).first.wait_for(state="visible"),
                        page.locator("input[placeholder*='дд.мм']").filter(visible=True).first.wait_for(state="visible")
                    ]
                    # Ждем, пока сработает ХОТЯ БЫ ОДНА (return_when=asyncio.FIRST_COMPLETED)
                    # Playwright методы wait_for возвращают None, поэтому используем wait
                    done, pending = await asyncio.wait(
                        [asyncio.create_task(t) for t in tasks], 
                        timeout=8.0, 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Отменяем невыполненные задачи
                    for p in pending: p.cancel()
                    
                    if done:
                        log.info("✅ Панель визуально подтверждена.")
                        anchor_found = True
                        break
                except Exception:
                    pass

                if not anchor_found:
                    log.warning(f"⚠️ Попытка {attempt+1}: Панель не обнаружена, повторяем клик...")
                    await page.keyboard.press("Escape") # Снимаем возможные оверлеи
                    await btn_requisites.click(force=True)
                    await page.wait_for_timeout(2000)

            if not anchor_found:
                raise Exception("Не удалось обнаружить панель реквизитов даже после повторных попыток")

            # Даем финальное время на анимацию и JS для полной готовности всех полей
            log.info("Ожидание стабилизации интерфейса...")
            await page.wait_for_timeout(2000)

            # --- V3.9 АБСОЛЮТНЫЙ СНАЙПЕР: Якоря "Категория дела" и "Суд" ---
            # Больше не полагаемся на изоляцию панели, ищем по визуальной иерархии

            # 2. Установка дат 2025-2026 (Якорь: Категория дела)
            log.info("Установка фильтра дат (поиск над 'Категория дела')...")
            try:
                # Ожидаем якорь "Категория дела"
                anchor_cat = page.get_by_text("Категория дела").filter(visible=True).first
                await anchor_cat.wait_for(state="visible", timeout=7000)
                
                # Даты находятся ВЫШЕ категории дела в DOM. Ищем инпуты с дд.мм над этим текстом.
                # XPath находит все инпуты-предшественники в документе, мы берем последние два (ближайшие сверху)
                date_inputs = page.locator("xpath=//div[contains(text(), 'Категория дела')]/preceding::input[contains(@placeholder, 'дд.мм') or contains(@placeholder, 'гггг')]")
                
                count = await date_inputs.count()
                if count >= 2:
                    # Ближайшие к тексту инпуты будут последними в списке preceding
                    d_to = date_inputs.nth(count - 1)
                    d_from = date_inputs.nth(count - 2)
                    
                    log.info(f"✅ Найдено полей даты над якорем: 2")
                    await d_from.scroll_into_view_if_needed()
                    await d_from.click(force=True)
                    await d_from.clear()
                    await d_from.type("01.01.2025", delay=75)
                    
                    await d_to.click(force=True)
                    await d_to.clear()
                    await d_to.type("31.12.2026", delay=75)
                    log.info("✅ Даты установлены.")
                else:
                    raise Exception(f"Найдено недостаточно инпутов над якорем (всего: {count})")
            except Exception as e:
                log.warning(f"⚠️ Сбой поиска по якорю 'Категория дела': {e}. Пробуем глобальный поиск...")
                # Фолбэк на глобальный поиск по всей странице
                global_dates = page.locator("input[placeholder*='дд.мм']").filter(visible=True)
                if await global_dates.count() >= 2:
                    await global_dates.nth(0).type("01.01.2025", delay=75)
                    await global_dates.nth(1).type("31.12.2026", delay=75)
                    log.info("✅ Даты установлены (глобальный поиск).")
                else:
                    log.error("❌ Даты не установлены.")

            # 3. Выбор Верховного суда РФ (Якорь: Суд)
            log.info("Выбор Верховного суда РФ (поиск триггера в секции 'Суд')...")
            try:
                # Ищем текст "Суд" и первый "Любой" за ним
                court_anchor = page.get_by_text("Суд").filter(visible=True).first
                await court_anchor.wait_for(state="visible", timeout=5000)
                
                # Находим "Любой" в том же блоке или сразу после него
                court_trigger = page.locator("xpath=//div[contains(text(), 'Суд') or contains(., 'Суд')]/following::*[contains(text(), 'Любой')]").filter(visible=True).first
                
                await court_trigger.scroll_into_view_if_needed()
                await court_trigger.click(force=True)
                log.info("Клик по 'Любой' выполнен.")
                
                await page.wait_for_timeout(2500) # Ждем оверлей
                
                # Выбор пункта
                target_court = page.get_by_text("Верховный суд РФ", exact=True).filter(visible=True).first
                await target_court.wait_for(state="visible", timeout=10000)
                await target_court.click(force=True)
                log.info("✅ Верховный суд РФ выбран.")
            except Exception as e:
                log.error(f"❌ Ошибка выбора суда: {e}")
                # Пробуем нажать любой видимый "Любой" и найти ВС РФ
                try:
                    await page.get_by_text("Любой").filter(visible=True).first.click(force=True)
                    await page.get_by_text("Верховный суд РФ", exact=True).filter(visible=True).first.click(force=True, timeout=5000)
                except: pass

            # 4. Ввод ключевых слов и запуск
            log.info(f"Ввод запроса: {keywords}...")
            # В расширенном поиске используем поле "Найти документы с текстом"
            await page.get_by_placeholder("Поиск документов").fill(keywords)
            await page.keyboard.press("Enter")
            
            log.info("🎯 Все фильтры применены! Поиск ВС РФ (2025-2026) запущен.")

        except Exception as e:
            log.error(f"❌ Сбой автоматизации: {e}")

        print("\nДля выхода нажмите Ctrl+C в терминале.")
        try: await asyncio.Future()
        except asyncio.CancelledError: pass

if __name__ == "__main__":
    try: asyncio.run(run_automation())
    except KeyboardInterrupt: pass