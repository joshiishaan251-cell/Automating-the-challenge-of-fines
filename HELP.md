# 🎮 Your LegalTech Remote: Profiler Orchestrator

Hi! Now you have **main.py** — it's like a main hub or a super-app that controls all your scripts. You no longer need to run through folders; everything is launched from one place.

Here's your checklist on how to work with it and not break the internet:

### 1. How to start this "machine"? 🚀
There are two ways:
1.  **Double-click the desired file** in the folder (the easiest way):
    *   `run_sorter.bat` — starts sorting.
    *   `run_payments.bat` — starts payments.
    *   `run_statement.bat` — starts statements.
    *   `run_index_uin.bat` — starts UIN indexing.
    *   `run_1_0.bat` — starts processing resolutions (Module 1_0).
2.  Or via terminal: `python main.py [module_name]`

### 2. List of available "skills":
*   **sorter** — when you need to distribute a bunch of court acts and checks into folders in the archive.
*   **payments** — if you need to quickly sort payments.
*   **statement** — when a bank statement ("dirty" PDF) arrives and needs to be turned into a "clean" report with money recalculation.
*   **index_uin** — scanning archives and creating a database of challenged UINs (SQLite).
*   **1_0** — semi-automatic processing of resolution scans: recognition (UIN, date, car), duplicate check, and auto-generation of court applications.

### 3. Quick Start (Your Action Plan):
- [ ] **Step 1: Connect.** Open PowerShell or CMD where `main.py` is located.
- [ ] **Step 2: Choose a task.** 
    - Need to sort the archive? Type: `python main.py sorter`
    - Need to process a bank statement? Type: `python main.py statement`
    - Need to prepare applications for new resolutions? Type: `python main.py 1_0`
- [ ] **Step 3: Check the result.** After launching, the script itself will tell you if everything is OK. If you want to see details, look in the `logs/orchestrator.log` folder — the entire history of its adventures is stored there.

### 4. What to do if "everything fell"? 🆘
*   If the command doesn't work, check if you wrote the module name correctly (no mistakes!).
*   Look in `orchestrator_config.yaml` — these are the "brains" of the system. It specifies where all the scripts are.
*   Remember about **Dry Run** (rehearsal mode) — it might be enabled in module configs so the script doesn't move anything, but just shows what it plans to do.

### 5. Pro Tip:
If you don't remember the commands, just type `python main.py --help`. It will tell you what it can do.

**Let's go! 🦾**
