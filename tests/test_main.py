import pytest
from main import load_config
import os

def test_config_loading():
    # Ensure orchestrator_config.yaml exists and loads correctly
    config = load_config()
    assert 'modules' in config
    assert 'sorter' in config['modules']
    assert 'payments' in config['modules']
    assert 'statement' in config['modules']

def test_module_paths():
    config = load_config()
    for name, m_cfg in config['modules'].items():
        # Check if the path defined in config actually exists
        # Note: In a real test environment, we'd mock the filesystem, 
        # but here we check against the actual project structure.
        path = m_cfg.get('path')
        if path:
            assert os.path.exists(path), f"Module {name} path {path} does not exist"

def test_logging_config():
    config = load_config()
    assert 'logging' in config
    assert 'file' in config['logging']
