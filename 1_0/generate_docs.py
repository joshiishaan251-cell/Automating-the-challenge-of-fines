import os
import sys
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime

# --- CONFIGURATION (Passed from main script to avoid circular import) ---
LIBREOFFICE_PATH = r"C:\Program Files\LibreOffice\program\soffice.exe"
TEMPLATE_PATH = None
TEMPLATE_NAME = 'ShablonZayavlenie.docx'

def load_database(folder_path):
    db_path = folder_path / "BASE" / "database.json"
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}")
        return None
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading database: {e}")
        return None

def fill_template(template_path, output_path, data):
    """Fills placeholders in DOCX while preserving formatting."""
    try:
        from docx import Document
    except ImportError:
        print("python-docx library not installed. Install it: pip install python-docx")
        return False

    def docx_replace(container, replacements):
        """Safe replace that preserves formatting by iterating through runs."""
        for p in getattr(container, 'paragraphs', []):
            for key, val in replacements.items():
                if key in p.text:
                    # Iterate through runs to replace text without destroying formatting
                    found = False
                    for run in p.runs:
                        if key in run.text:
                            run.text = run.text.replace(key, str(val))
                            found = True
                    
                    # Fallback: if key is in paragraph but not in any single run,
                    # it means Word split the placeholder across multiple runs.
                    if not found and p.runs:
                        new_text = p.text.replace(key, str(val))
                        p.runs[0].text = new_text
                        for i in range(1, len(p.runs)):
                            p.runs[i].text = ""
                    
                    print(f"  [Replacement] '{key}' -> '{str(val)[:40]}'")
                            
        for table in getattr(container, 'tables', []):
            for row in table.rows:
                for cell in row.cells:
                    docx_replace(cell, replacements) # Recurse for cells

    try:
        doc = Document(template_path)
        replacements = {
            "{{CASE_NUMBERS}}": ", ".join(data.get("CaseNumbers", [])),
            "{{VEHICLE_NUMBERS}}": ", ".join(data.get("VehicleNumbers", [])),
            "{{POCHTA_NUMBER}}": data.get("PochtaNumber", ""),
            "{{DATA_NUMBER}}": data.get("DataNumber", ""),
            # Fallbacks if placeholders are used without braces
            "CASE_NUMBERS": ", ".join(data.get("CaseNumbers", [])),
            "VEHICLE_NUMBERS": ", ".join(data.get("VehicleNumbers", [])),
            "POCHTA_NUMBER": data.get("PochtaNumber", ""),
            "DATA_NUMBER": data.get("DataNumber", "")
        }

        docx_replace(doc, replacements)

        # Handle headers/footers
        for section in doc.sections:
            for header in [section.header, section.first_page_header, section.even_page_header]:
                if header: docx_replace(header, replacements)
            for footer in [section.footer, section.first_page_footer, section.even_page_footer]:
                if footer: docx_replace(footer, replacements)

        doc.save(output_path)
        return True
    except Exception as e:
        print(f"Error filling template: {e}")
        return False

def get_page_count(doc_obj):
    """Estimate page count from DOCX properties."""
    try:
        return doc_obj.core_properties.pages if doc_obj.core_properties.pages else None
    except:
        return None

def convert_to_pdf(docx_path, output_dir):
    if not os.path.exists(LIBREOFFICE_PATH):
        print(f"Error: LibreOffice not found at {LIBREOFFICE_PATH}")
        return False
    
    try:
        print(f"Converting to PDF: {docx_path.name}...")
        cmd = [
            LIBREOFFICE_PATH,
            "--headless",
            "--convert-to", "pdf",
            str(docx_path),
            "--outdir", str(output_dir)
        ]
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        print(f"Error converting to PDF: {e}")
        return False

def generate_for_folder(folder_path, config=None):
    if config:
        global LIBREOFFICE_PATH, TEMPLATE_NAME, TEMPLATE_PATH
        LIBREOFFICE_PATH = config.get('libreoffice_path', LIBREOFFICE_PATH)
        TEMPLATE_NAME = config.get('template_name', TEMPLATE_NAME)
        TEMPLATE_PATH = config.get('template_path')

    folder_path = Path(folder_path)
    print(f"\n--- Generating documents for: {folder_path.name} ---")
    
    data = load_database(folder_path)
    if not data:
        return

    # Diagnostic: print what we loaded
    print(f"  DataNumber  in DB: {data.get('DataNumber', '[NONE]')}")
    print(f"  PochtaNumber in DB: {data.get('PochtaNumber', '[NONE]')}")
    print(f"  CaseNumbers  in DB: {data.get('CaseNumbers', '[NONE]')}")

    if TEMPLATE_PATH and Path(TEMPLATE_PATH).exists():
        template_path = Path(TEMPLATE_PATH)
    else:
        template_path = folder_path.parent / TEMPLATE_NAME
        if not template_path.exists():
            # Try local folder too
            template_path = folder_path / TEMPLATE_NAME
            if not template_path.exists():
                print(f"Error: Template not found: {template_path}")
                return

    # Prepare output filenames
    folder_name_clean = re.sub(r'[<>:"/\\|?*]', '', folder_path.name)
    
    # Create final document
    output_docx_temp = folder_path / f"temp_gen.docx"
    if fill_template(template_path, output_docx_temp, data):
        page_count_str = ""
        try:
            from docx import Document
            temp_doc = Document(output_docx_temp)
            page_count = get_page_count(temp_doc)
            if page_count:
                page_count_str = f"-{page_count}p"
        except:
            pass
        
        final_base_name = f"Appeal against resolution {folder_name_clean}{page_count_str}"
        output_docx = folder_path / f"{final_base_name}.docx"
        output_pdf = folder_path / f"{final_base_name}.pdf"
        
        if output_docx.exists(): os.remove(output_docx)
        os.rename(output_docx_temp, output_docx)
        
        if convert_to_pdf(output_docx, folder_path):
            print(f"Successfully created:\n- {output_docx.name}\n- {output_pdf.name}")
        else:
            print("Only DOCX created, PDF conversion error.")
    else:
        print("Error generating documents.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_for_folder(sys.argv[1])
    else:
        generate_for_folder(os.getcwd())
