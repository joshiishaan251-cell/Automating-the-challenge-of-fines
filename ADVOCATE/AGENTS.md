---
name: "LegalTech Automation Pipeline"
description: "Lawyer automation system: document parsing, claim generation, and automated search for judicial practice (Supreme Court of the RF, ConsultantPlus, 1jur)."
category: "LegalTech / Local Automation"
author: "Logik (Wipe-coder)"
tags: ["python", "legaltech", "ocr", "automation", "zero-trust"]
---

# 🏛️ LegalTech Automation Pipeline

## 🎯 Global Project Context
We are developing a fault-tolerant local Python system to automate a lawyer's work.
**Domain Specifics:** The cost of error is critical. A typo in an amount or an incorrect case number leads to losing in court.
**Main Rule (Zero Trust):** Silent errors are unacceptable. If data is unclear, the system must "crash loudly" (Exception) or move the file to `manual_review`. It is forbidden to delete or overwrite the lawyers' original source files!

## 🛠 Technology Stack
- **Language:** Python 3.10+ (Strict typing: `typing`, `dataclasses`).
- **Text Extraction (OCR):** `pdfplumber`, `pdf2image`, `pytesseract` (Russian language pack).
- **Document Generation:** `python-docx`, `num2words` (for amounts in words).
- **OS Interaction:** `pathlib` (strictly for paths), `subprocess` (for launching the browser).
- **Testing:** `pytest`.

## ⚙️ System Constants and Environment
- **Browser for legal databases:** Strictly Chromium-Gost.
  `CHROMIUM_PATH = r"C:\Users\Logik\AppData\Local\Chromium\Application\chrome.exe"`
- **Tesseract OCR Path:**
  `TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"`
- **Poppler Path:**
  `POPPLER_BIN_PATH = r"C:\poppler\Library\bin"`

## 🤖 Instructions for the AI Agent (You)

### 1. Coding Rules
- Always wrap file read/write blocks and API requests in `try-except`. Log errors using the `logging` module.
- Use `pathlib.Path` instead of `os.path`.
- Always format amounts in templates (DOCX) with thousands separators (e.g., `1 500 000.00`).

### 2. Workflows
The agent should use the following prompt modules upon user request:
- **Case Analysis:** When referencing `analyze_case.md`, the agent writes an OCR script to dump text into `case_text_dump.txt` and analyzes it, identifying the Customer, Carrier, and amounts.
- **Practice Search (Consultant/1jur):** The agent must write a script that takes keywords from `case_text_dump.txt`, forms correct search URLs, and opens them in new tabs strictly via `CHROMIUM_PATH`.
- **Claim Generation:** When referencing `claim_template.md`, the agent uses `python-docx` for safe text replacement without breaking table formatting.

### 3. Testing and Review (Mandatory Phase)
- **Tests (`test_parser.md`):** Any new logic (parsing, URL generation) must be covered by `pytest` using `io.BytesIO` (in memory) to avoid cluttering the disk. Boundary cases (typos, data conflicts) must be checked.
- **Skeptic (`devil_advocate.md`):** At the end of each major phase, the agent must conduct a ruthless review of its code for hidden debt and violations of the "Zero Trust" rule.

---
*Reminder to Agent: Never invent (hallucinate) legal facts. If data is missing, return an error.*