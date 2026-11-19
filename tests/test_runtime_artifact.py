import tempfile
import unittest
from pathlib import Path

from scripts.runtime_artifact import validate_runtime_artifact


def artifact(root: str):
    return {
        "plugin": {
            "name": "us-app-donchian-ema",
            "version": "lab-source",
            "python_root": root,
            "entrypoint": "strategy_plugins.us_app_plugin:USAppStrategyPlugin",
            "constructor": {"lab_root": root},
        },
        "params": {"fast": 12, "slow": 35},
        "interval": 10,
        "mode": "SIMULATE",
        "promotion": {
            "baseline": {"total_return_pct": 1.0},
            "candidate": {"total_return_pct": 2.0},
            "replay_protocol": "first_21_complete_sessions_then_one_continuous_unseen_replay",
        },
    }


class RuntimeArtifactTests(unittest.TestCase):
    def test_valid_artifact_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(validate_runtime_artifact(artifact(root)), artifact(root))

    def test_live_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            payload = artifact(root)
            payload["mode"] = "LIVE"
            with self.assertRaises(ValueError):
                validate_runtime_artifact(payload)

    def test_extra_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            payload = artifact(root)
            payload["unexpected"] = True
            with self.assertRaises(ValueError):
                validate_runtime_artifact(payload)

    def test_missing_root_is_rejected(self):
        payload = artifact("/path/that/does/not/exist")
        with self.assertRaises(ValueError):
            validate_runtime_artifact(payload)


if __name__ == "__main__":
    unittest.main()
