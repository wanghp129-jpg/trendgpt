from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendgpt.browser_registry import instance_for_role, load_browser_registry, validate_browser_registry
from trendgpt.contracts import ContractError


class BrowserRegistryTests(unittest.TestCase):
    def fixture(self):
        return {
            "schema": "trendgpt-browser-instances-v1",
            "instances": [
                {"name": "source", "port": 9226, "role": "trends_source_collection",
                 "status": "planned_not_configured", "chatgpt_account": False, "concurrency": "single_owner"},
                {"name": "cleaner", "port": 9227, "role": "trends_keyword_cleaning",
                 "status": "planned_not_configured", "chatgpt_account": True, "concurrency": "single_owner"},
            ],
            "chatgpt_global_lock": {
                "path": "/tmp/chatgpt-global.lock", "required_for_all_chatgpt_callers": True,
            },
        }

    def test_valid_registry_keeps_9226_9227_as_planned(self):
        data = self.fixture()
        self.assertEqual(instance_for_role(data, "trends_keyword_cleaning")["port"], 9227)
        self.assertEqual(data["instances"][0]["status"], "planned_not_configured")

    def test_duplicate_port_is_rejected(self):
        data = self.fixture()
        data["instances"][1]["port"] = 9226
        with self.assertRaises(ContractError):
            validate_browser_registry(data)

    def test_registry_file_load(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registry.json"
            path.write_text(json.dumps(self.fixture()), encoding="utf-8")
            self.assertEqual(len(load_browser_registry(path)["instances"]), 2)


if __name__ == "__main__":
    unittest.main()
