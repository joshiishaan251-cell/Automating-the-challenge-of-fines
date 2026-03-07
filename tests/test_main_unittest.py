import unittest
import os
import sys
from main import load_config

class TestOrchestrator(unittest.TestCase):
    def test_config_loading(self):
        config = load_config()
        self.assertIn('modules', config)
        self.assertIn('sorter', config['modules'])
        self.assertIn('payments', config['modules'])
        self.assertIn('statement', config['modules'])

    def test_module_paths(self):
        config = load_config()
        for name, m_cfg in config['modules'].items():
            path = m_cfg.get('path')
            if path:
                self.assertTrue(os.path.exists(path), f"Module {name} path {path} does not exist")

    def test_logging_config(self):
        config = load_config()
        self.assertIn('logging', config)
        self.assertIn('file', config['logging'])

if __name__ == '__main__':
    unittest.main()
