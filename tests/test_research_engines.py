import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import session_monitor
from scripts.competition_bot import CompetitionBot
from scripts.causal_formula_engine import run_formula
from scripts.custom_indicator_engine import run_custom
from scripts.ml_strategy_engine import run_ml


def candles(rows=80):
    index = pd.date_range("2026-01-02 09:31", periods=rows, freq="1min")
    close = pd.Series(100.0 + pd.RangeIndex(rows).to_numpy() * 0.15, index=index)
    return pd.DataFrame({
        "open": close - 0.05,
        "high": close + 0.25,
        "low": close - 0.25,
        "close": close,
        "volume": 1000.0,
    }, index=index)


class ResearchEngineTests(unittest.TestCase):
    def test_formula_engine_tuple_replay(self):
        frame = candles()
        spec = {
            "entry": {"op": "gt", "args": [{"op": "field", "name": "close"}, {"op": "const", "value": 100}]},
            "exit": {"op": "lt", "args": [{"op": "field", "name": "close"}, {"op": "const", "value": 0}]},
        }
        trades, data, stats = run_formula(frame, spec)
        self.assertIsNotNone(data["equity"])
        self.assertGreaterEqual(stats["trades"], 0)

    def test_custom_and_ml_tuple_replays(self):
        frame = candles()
        custom = {
            "features": [{"id": "ema", "name": "ema", "window": 5}],
            "entry": {"op": "gt", "left": "ema", "right": 0},
            "exit": {"op": "lt", "left": "ema", "right": 0},
        }
        _, _, custom_stats = run_custom(frame, custom)
        _, _, ml_stats = run_ml(frame, {"model": "formula", "feature_window": 5, "min_train": 20})
        self.assertIn("ending_cash", custom_stats)
        self.assertIn("ending_equity", ml_stats)


class SupervisorAndHotSwapTests(unittest.TestCase):
    def test_supervisor_starts_missing_services(self):
        started = []
        with patch.object(session_monitor, "processes", return_value=[]), \
             patch.object(session_monitor, "account_id", return_value=123), \
             patch.object(session_monitor, "start", side_effect=lambda command, label: started.append((command, label))):
            session_monitor.ensure_processes()
        self.assertEqual([label for _, label in started], ["strategy lab", "research console", "paper bot"])
        self.assertIn("--continuous", started[0][0])
        self.assertIn("--live-paper", started[2][0])

    def test_supervisor_stops_only_duplicate_processes(self):
        with patch.object(session_monitor, "processes", return_value=[(10, "python bot"), (20, "python bot")]), \
             patch.object(session_monitor, "stop") as stop:
            session_monitor.keep_one("bot")
        stop.assert_called_once_with(20)

    def test_plugin_hot_swap_loads_paper_contract(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            package = root_path / "strategy_plugins"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "fake.py").write_text(
                "class FakePlugin:\n"
                "    baseline = {'fast': 3}\n"
                "    def __init__(self, lab_root=None): self.lab_root = lab_root\n"
                "    def strategy_signal(self, frame, params): return {}\n"
                "    def profit_capture_exit(self, *args, **kwargs): return False\n"
                "    def aggregate_candles(self, frame, interval): return frame\n"
            )
            config = root_path / "runtime.json"
            config.write_text("{}")
            payload = {
                "plugin": {
                    "name": "test-plugin",
                    "version": "test",
                    "python_root": str(root_path),
                    "entrypoint": "strategy_plugins.fake:FakePlugin",
                    "constructor": {"lab_root": str(root_path)},
                },
                "params": {"fast": 5},
                "interval": 1,
                "mode": "SIMULATE",
                "promotion": {
                    "baseline": {"total_return_pct": 1},
                    "candidate": {"total_return_pct": 2},
                    "replay_protocol": "first_21_complete_sessions_then_one_continuous_unseen_replay",
                },
            }
            bot = object.__new__(CompetitionBot)
            bot.strategy_baseline = {}
            bot.strategy_config_signature = None
            bot.strategy_params = {}
            with patch.object(bot, "_load_strategy_params", return_value={"fast": 5}):
                self.assertTrue(bot._load_plugin_runtime(payload, config))
            self.assertEqual(bot.strategy_params, {"fast": 5})
            self.assertEqual(bot.strategy_baseline, {"fast": 3})


if __name__ == "__main__":
    unittest.main()
