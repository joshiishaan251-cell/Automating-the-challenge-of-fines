import argparse
import logging
import os
import subprocess
import sys
import yaml

# --- GLOBAL CONFIGURATION ---
CONFIG_FILE = "orchestrator_config.yaml"

def setup_logging(config):
    log_cfg = config.get('logging', {})
    log_file = log_cfg.get('file', 'logs/orchestrator.log')
    log_level = log_cfg.get('level', 'INFO')
    
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_cfg.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("Orchestrator")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Configuration file {CONFIG_FILE} not found.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def run_module(module_name, config, logger, extra_args=None):
    module_cfg = config.get('modules', {}).get(module_name)
    if not module_cfg:
        logger.error(f"Module '{module_name}' not found in configuration.")
        return False

    script_path = module_cfg.get('path')
    working_dir = module_cfg.get('working_dir') or os.path.dirname(script_path)
    
    # Absolute path for the script
    abs_script_path = os.path.abspath(script_path)
    
    logger.info(f"Starting module: {module_name} ({module_cfg.get('description', '')})")
    logger.info(f"Executing: {abs_script_path} in {working_dir}")

    try:
        # Use sys.executable to ensure the same interpreter is used
        cmd = [sys.executable, abs_script_path]
        if extra_args:
            cmd.extend(extra_args)
            
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=False, # We want to see the output in the terminal
            text=True,
            check=True
        )
        logger.info(f"Module '{module_name}' finished successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Module '{module_name}' failed with return code {e.returncode}.")
        return False
    except Exception as e:
        logger.error(f"Error running module '{module_name}': {e}")
        return False

def main():
    config = load_config()
    logger = setup_logging(config)
    
    parser = argparse.ArgumentParser(description="LegalTech Automation Orchestrator")
    subparsers = parser.add_subparsers(dest="command", help="Available modules")

    # Dynamically register subcommands from config
    modules = config.get('modules', {})
    for name, cfg in modules.items():
        subparsers.add_parser(name, help=cfg.get('description', ''))

    args, unknown = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    success = run_module(args.command, config, logger, extra_args=unknown)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
