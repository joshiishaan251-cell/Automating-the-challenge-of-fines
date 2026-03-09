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
    print("Error: pip install playwright google-generativeai python-dotenv")
    exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# Resource settings according to AGENTS.md
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
    """Extracts the essence of the dispute without extra noise."""
    log.info("🤖 AI analyzing document essence...")
    genai.configure(api_key=API_KEY)
    # Using full path to model for stability
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    prompt = f"Identify 2-4 keywords for searching legal practice (without dates/courts): {text[:2500]}"
    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text.strip().replace('"', '')
    except Exception:
        return "debt collection under transportation contract"

async def run_automation():
    exe_path, data_path = find_resources()
    if not exe_path: return

    case_text = TEXT_DUMP.read_text(encoding="utf-8") if TEXT_DUMP.exists() else "transportation"
    keywords = await get_refined_query(case_text)
    log.info(f"✅ KEYWORDS: {keywords}")

    async with async_playwright() as p:
        log.info(f"🚀 Launching {exe_path.name} (Fullscreen mode)...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(data_path) if data_path else "",
            executable_path=str(exe_path),
            headless=False,
            no_viewport=True, # Fullscreen window
            args=["--no-first-run", "--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"]
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        log.info("Navigating to Judicial Practice section 1jur.ru...")
        await page.goto("https://1jur.ru/#/lawpractice/", wait_until="networkidle")

        try:
            # 1. Activate "BY REQUISITES" panel
            log.info("Activating advanced search...")
            # Search all buttons for diagnostics
            btns = page.get_by_text("ПО РЕКВИЗИТАМ").filter(visible=True)
            log.info(f"Found 'BY REQUISITES' buttons: {await btns.count()}")
            
            btn_requisites = btns.first
            await btn_requisites.scroll_into_view_if_needed()
            await btn_requisites.hover()
            await btn_requisites.click(force=True)
            
            # Wait for AT LEAST ONE visual anchor to appear
            log.info("Waiting for any sign of panel opening...")
            anchor_found = False
            for attempt in range(3):
                try:
                    # Create tasks to wait for various elements
                    tasks = [
                        page.get_by_text("только точную фразу").filter(visible=True).first.wait_for(state="visible"),
                        page.get_by_text("Вид").filter(visible=True).first.wait_for(state="visible"),
                        page.locator("input[placeholder*='дд.мм']").filter(visible=True).first.wait_for(state="visible")
                    ]
                    # Wait until AT LEAST ONE fires (return_when=asyncio.FIRST_COMPLETED)
                    # Playwright wait_for methods return None, so we use wait
                    done, pending = await asyncio.wait(
                        [asyncio.create_task(t) for t in tasks], 
                        timeout=8.0, 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel uncompleted tasks
                    for p in pending: p.cancel()
                    
                    if done:
                        log.info("✅ Panel visually confirmed.")
                        anchor_found = True
                        break
                except Exception:
                    pass

                if not anchor_found:
                    log.warning(f"⚠️ Attempt {attempt+1}: Panel not detected, retrying click...")
                    await page.keyboard.press("Escape") # Close possible overlays
                    await btn_requisites.click(force=True)
                    await page.wait_for_timeout(2000)

            if not anchor_found:
                raise Exception("Failed to detect requisites panel even after repeated attempts")

            # Final time for animation and JS to ready all fields
            log.info("Waiting for interface stabilization...")
            await page.wait_for_timeout(2000)

            # --- V3.9 ABSOLUTE SNIPER: Anchors "Case Category" and "Court" ---
            # No longer rely on panel isolation, search by visual hierarchy

            # 2. Set dates 2025-2026 (Anchor: Case Category)
            log.info("Setting date filter (search above 'Case Category')...")
            try:
                # Wait for anchor "Case Category"
                anchor_cat = page.get_by_text("Категория дела").filter(visible=True).first
                await anchor_cat.wait_for(state="visible", timeout=7000)
                
                # Dates are ABOVE case category in DOM. Searching for inputs with dd.mm above this text.
                # XPath finds all predecessor inputs in document, we take last two (nearest from above)
                date_inputs = page.locator("xpath=//div[contains(text(), 'Категория дела')]/preceding::input[contains(@placeholder, 'дд.мм') or contains(@placeholder, 'гггг')]")
                
                count = await date_inputs.count()
                if count >= 2:
                    # Nearest inputs to text will be last in preceding list
                    d_to = date_inputs.nth(count - 1)
                    d_from = date_inputs.nth(count - 2)
                    
                    log.info(f"✅ Found date fields above anchor: 2")
                    await d_from.scroll_into_view_if_needed()
                    await d_from.click(force=True)
                    await d_from.clear()
                    await d_from.type("01.01.2025", delay=75)
                    
                    await d_to.click(force=True)
                    await d_to.clear()
                    await d_to.type("31.12.2026", delay=75)
                    log.info("✅ Dates established.")
                else:
                    raise Exception(f"Insufficient inputs found above anchor (total: {count})")
            except Exception as e:
                log.warning(f"⚠️ Search by 'Case Category' anchor failed: {e}. Trying global search...")
                # Fallback to global search across entire page
                global_dates = page.locator("input[placeholder*='дд.мм']").filter(visible=True)
                if await global_dates.count() >= 2:
                    await global_dates.nth(0).type("01.01.2025", delay=75)
                    await global_dates.nth(1).type("31.12.2026", delay=75)
                    log.info("✅ Dates established (global search).")
                else:
                    log.error("❌ Dates not set.")

            # 3. Select Supreme Court of RF (Anchor: Court)
            log.info("Selecting Supreme Court of RF (searching trigger in 'Court' section)...")
            try:
                # Searching for text "Court" and first "Any" after it
                court_anchor = page.get_by_text("Суд").filter(visible=True).first
                await court_anchor.wait_for(state="visible", timeout=5000)
                
                # Find "Any" in the same block or right after it
                court_trigger = page.locator("xpath=//div[contains(text(), 'Суд') or contains(., 'Суд')]/following::*[contains(text(), 'Любой')]").filter(visible=True).first
                
                await court_trigger.scroll_into_view_if_needed()
                await court_trigger.click(force=True)
                log.info("Click on 'Any' completed.")
                
                await page.wait_for_timeout(2500) # Wait for overlay
                
                # Select item
                target_court = page.get_by_text("Верховный суд РФ", exact=True).filter(visible=True).first
                await target_court.wait_for(state="visible", timeout=10000)
                await target_court.click(force=True)
                log.info("✅ Supreme Court of RF selected.")
            except Exception as e:
                log.error(f"❌ Error selecting court: {e}")
                # Try clicking any visible "Any" and find SC RF
                try:
                    await page.get_by_text("Любой").filter(visible=True).first.click(force=True)
                    await page.get_by_text("Верховный суд РФ", exact=True).filter(visible=True).first.click(force=True, timeout=5000)
                except: pass

            # 4. Input keywords and start
            log.info(f"Inputting query: {keywords}...")
            # In advanced search use "Find documents with text" field
            await page.get_by_placeholder("Поиск документов").fill(keywords)
            await page.keyboard.press("Enter")
            
            log.info("🎯 All filters applied! Search for SC RF (2025-2026) launched.")

        except Exception as e:
            log.error(f"❌ Automation crash: {e}")

        print("\nPress Ctrl+C in terminal to exit.")
        try: await asyncio.Future()
        except asyncio.CancelledError: pass

if __name__ == "__main__":
    try:
        asyncio.run(run_automation())
    except KeyboardInterrupt:
        pass