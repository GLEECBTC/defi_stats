"""Offline regression tests: no Docker, GitHub, or Telegram calls."""

from contextlib import contextmanager
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from coins_monitoring import coins_monitoring as monitor


OLD = "a" * 40
NEW = "b" * 40
LATEST = "c" * 40
COINS = {
    OLD: ["BTC", "LTC", "OLDCOIN"],
    NEW: ["BTC", "LTC", "USDS-BASE", "USDS-ERC20"],
    LATEST: ["BTC", "LTC", "USDS-ARB20", "USDS-BASE", "USDS-ERC20"],
}


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state_path = self.root / "monitor.state.json"
        self.cfg = monitor.load_config(monitor.SCRIPT.with_suffix(".ini.example"), require_token=False)
        self.cfg.update(bot_token="12345:TEST_TOKEN", github_token="", project_dir=str(self.root))

    def baseline(self, pending=None, legacy=False):
        state = {
            "version": 1, "target": monitor.target_identity(self.cfg),
            "last_sha": OLD, "pending": pending or [],
        }
        if not legacy:
            state["coins_by_commit"] = {OLD: COINS[OLD]}
        monitor.save_state(self.state_path, state)

    def state(self):
        return monitor.read_state(self.state_path, self.cfg)

    @contextmanager
    def external(self, head=NEW):
        with patch.object(monitor, "get_head", return_value=head) as github, \
                patch.object(monitor, "get_coins", side_effect=lambda cfg, sha: COINS[sha][:]), \
                patch.object(monitor, "restart_service") as restart, \
                patch.object(monitor, "send_telegram") as telegram:
            yield github, restart, telegram

    def test_first_run_only_initializes(self):
        with self.external() as (_, restart, telegram):
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            restart.assert_not_called()
            telegram.assert_not_called()
        self.assertEqual(self.state()["last_sha"], NEW)
        self.assertEqual(self.state()["coins_by_commit"], {NEW: COINS[NEW]})

    def test_unchanged_does_not_restart(self):
        self.baseline()
        with self.external(OLD) as (_, restart, telegram):
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            restart.assert_not_called()
            telegram.assert_not_called()

    def test_change_restarts_and_persists_before_notification(self):
        self.baseline()
        with self.external() as (_, restart, telegram):
            def inspect_saved_state(cfg, message):
                self.assertEqual(self.state()["last_sha"], NEW)
                self.assertEqual(self.state()["pending"], [message])
                self.assertIn(OLD, message)
                self.assertIn(NEW, message)
                self.assertIn("completed successfully", message)
                self.assertIn("Added coins (2):\n+ USDS-BASE\n+ USDS-ERC20", message)
                self.assertIn("Removed coins (1):\n- OLDCOIN", message)
                self.assertEqual(self.state()["coins_by_commit"], {OLD: COINS[OLD], NEW: COINS[NEW]})
            telegram.side_effect = inspect_saved_state
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            restart.assert_called_once_with(self.cfg)
        self.assertEqual(self.state()["pending"], [])

    def test_failed_restart_preserves_baseline_and_retries(self):
        self.baseline()
        with self.external() as (_, restart, telegram):
            restart.side_effect = monitor.MonitorError("Docker restart failed.")
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 1)
            self.assertEqual(self.state()["last_sha"], OLD)
            self.assertIn("failed", telegram.call_args.args[1])
            restart.side_effect = None
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            self.assertEqual(restart.call_count, 2)
        self.assertEqual(self.state()["last_sha"], NEW)

    def test_telegram_failure_retries_without_restarting_again(self):
        self.baseline()
        with self.external() as (_, restart, telegram):
            telegram.side_effect = monitor.MonitorError("Telegram unavailable.")
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 1)
            self.assertEqual(self.state()["last_sha"], NEW)
            self.assertEqual(len(self.state()["pending"]), 1)
            telegram.side_effect = None
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            restart.assert_called_once()
            self.assertEqual(telegram.call_count, 2)
        self.assertEqual(self.state()["pending"], [])

    def test_pending_failure_does_not_block_new_restart(self):
        self.baseline(pending=["An earlier notification."])
        with self.external(LATEST) as (_, restart, telegram):
            telegram.side_effect = monitor.MonitorError("Telegram unavailable.")
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 1)
            restart.assert_called_once()
        self.assertEqual(self.state()["last_sha"], LATEST)
        self.assertEqual(len(self.state()["pending"]), 2)

    def test_github_failure_does_not_change_baseline(self):
        self.baseline()
        before = self.state_path.read_bytes()
        with self.external() as (github, restart, telegram):
            github.side_effect = monitor.MonitorError("GitHub unavailable.")
            with self.assertRaises(monitor.MonitorError):
                monitor.run_check(self.cfg, self.state_path)
            restart.assert_not_called()
            telegram.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_dry_run_is_read_only_with_and_without_state(self):
        with self.external() as (_, restart, telegram):
            self.assertEqual(monitor.run_check(self.cfg, self.state_path, dry_run=True), 0)
            self.assertEqual(list(self.root.iterdir()), [])
            self.baseline(pending=["Do not send in dry run."])
            before = self.state_path.read_bytes()
            self.assertEqual(monitor.run_check(self.cfg, self.state_path, dry_run=True), 0)
            self.assertEqual(self.state_path.read_bytes(), before)
            restart.assert_not_called()
            telegram.assert_not_called()

    def test_corrupt_or_mismatched_state_is_not_overwritten(self):
        self.state_path.write_text("invalid JSON", encoding="utf-8")
        with self.external() as (github, restart, _):
            with self.assertRaises(monitor.MonitorError):
                monitor.run_check(self.cfg, self.state_path)
            github.assert_not_called()
            restart.assert_not_called()
        self.baseline()
        self.cfg["branch"] = "another-branch"
        with self.assertRaises(monitor.MonitorError):
            self.state()

    def test_state_write_failure_prevents_restart(self):
        self.baseline()
        with self.external() as (_, restart, _), \
                patch.object(monitor, "save_state", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                monitor.run_check(self.cfg, self.state_path)
            restart.assert_not_called()

    def test_overlapping_lock_is_rejected_and_released(self):
        lock_path = self.root / "monitor.lock"
        with monitor.single_instance(lock_path) as acquired:
            self.assertTrue(acquired)
            with monitor.single_instance(lock_path) as second:
                self.assertFalse(second)
        with monitor.single_instance(lock_path) as acquired:
            self.assertTrue(acquired)

    def test_restart_uses_exact_service_directory_and_no_shell(self):
        result = subprocess.CompletedProcess([], 0, "Restart completed", "")
        with patch.object(monitor.subprocess, "run", return_value=result) as run:
            monitor.restart_service(self.cfg)
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["/usr/bin/docker", "compose", "restart", "defi_stats"])
            self.assertEqual(kwargs["cwd"], str(self.root))
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")

    def test_restart_timeout_and_nonzero_exit(self):
        with patch.object(monitor.subprocess, "run", side_effect=subprocess.TimeoutExpired("docker", 1)):
            with self.assertRaisesRegex(monitor.MonitorError, "outcome is unknown"):
                monitor.restart_service(self.cfg)
        with patch.object(monitor.subprocess, "run", return_value=subprocess.CompletedProcess([], 2, "", "")):
            with self.assertRaisesRegex(monitor.MonitorError, "exit code 2"):
                monitor.restart_service(self.cfg)

    def test_http_error_does_not_expose_bot_token(self):
        url = f'https://api.telegram.org/bot{self.cfg["bot_token"]}/getMe'
        error = urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        with patch.object(monitor.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(monitor.MonitorError) as caught:
                monitor.send_telegram(self.cfg, "Test")
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn(self.cfg["bot_token"], str(caught.exception))

    def test_wrong_bot_is_rejected_before_send(self):
        with patch.object(monitor, "request_json", return_value={"ok": True, "result": {"username": "wrong_bot"}}) as request:
            with self.assertRaisesRegex(monitor.MonitorError, "configured bot"):
                monitor.send_telegram(self.cfg, "Test")
            request.assert_called_once()

    def test_telegram_uses_configured_chat_and_plain_text(self):
        identity = {"ok": True, "result": {"username": self.cfg["bot_username"]}}
        with patch.object(monitor, "request_json", side_effect=[identity, {"ok": True}]) as request:
            monitor.send_telegram(self.cfg, "Repository changed")
            payload = request.call_args.kwargs["payload"]
            self.assertEqual(payload["chat_id"], "-5100391257")
            self.assertEqual(payload["text"], "Repository changed")
            self.assertNotIn("parse_mode", payload)

    def test_github_ref_is_validated(self):
        data = {"ref": "refs/heads/master", "object": {"type": "commit", "sha": NEW}}
        with patch.object(monitor, "request_json", return_value=data):
            self.assertEqual(monitor.get_head(self.cfg), NEW)
            data["object"]["sha"] = "invalid"
            with self.assertRaises(monitor.MonitorError):
                monitor.get_head(self.cfg)

    def test_template_requires_token_except_for_dry_run(self):
        with self.assertRaisesRegex(monitor.MonitorError, "bot_token"):
            monitor.load_config(monitor.SCRIPT.with_suffix(".ini.example"))

    def test_legacy_state_fetches_previous_commit_without_resetting_baseline(self):
        self.baseline(legacy=True)
        with self.external() as (_, restart, telegram), \
                patch.object(monitor, "get_coins", side_effect=lambda cfg, sha: COINS[sha][:]) as coins:
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            self.assertEqual([call.args[1] for call in coins.call_args_list], [OLD, NEW])
            restart.assert_called_once()
            self.assertIn("+ USDS-BASE", telegram.call_args.args[1])
        self.assertEqual(self.state()["coins_by_commit"], {OLD: COINS[OLD], NEW: COINS[NEW]})

    def test_legacy_unchanged_state_fetches_and_saves_one_snapshot(self):
        self.baseline(pending=["Previously queued notification."], legacy=True)
        with self.external(OLD) as (_, restart, telegram), \
                patch.object(monitor, "get_coins", return_value=COINS[OLD]) as coins:
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            coins.assert_called_once_with(self.cfg, OLD)
            restart.assert_not_called()
            telegram.assert_called_once_with(self.cfg, "Previously queued notification.")
        self.assertEqual(self.state()["coins_by_commit"], {OLD: COINS[OLD]})

    def test_snapshot_download_failure_blocks_restart_and_keeps_baseline(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                self.baseline(legacy=legacy)
                before = self.state_path.read_bytes()
                with self.external() as (_, restart, telegram), \
                        patch.object(monitor, "get_coins", side_effect=monitor.MonitorError("Coins unavailable.")):
                    with self.assertRaises(monitor.MonitorError):
                        monitor.run_check(self.cfg, self.state_path)
                    restart.assert_not_called()
                    telegram.assert_not_called()
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_snapshots_are_retained_and_reused_after_failure_and_force_push(self):
        self.baseline()
        with self.external() as (github, restart, _), \
                patch.object(monitor, "get_coins", return_value=COINS[NEW]) as coins:
            restart.side_effect = monitor.MonitorError("Docker restart failed.")
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 1)
            self.assertEqual(self.state()["last_sha"], OLD)
            self.assertIn(NEW, self.state()["coins_by_commit"])
            restart.side_effect = None
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            github.return_value = OLD
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            coins.assert_called_once_with(self.cfg, NEW)
        self.assertEqual(self.state()["last_sha"], OLD)
        self.assertEqual(set(self.state()["coins_by_commit"]), {OLD, NEW})

    def test_get_coins_reads_full_identifiers_from_requested_sha(self):
        data = [{"coin": "USDS-ERC20"}, {"coin": "LTC-segwit"},
                {"coin": "USDS-BASE", "name": "Ignored metadata"}, {"coin": "USDS-BASE"}]
        with patch.object(monitor, "request_json", return_value=data) as request:
            self.assertEqual(monitor.get_coins(self.cfg, NEW), ["LTC-segwit", "USDS-BASE", "USDS-ERC20"])
            self.assertEqual(request.call_args.args[0],
                             f"https://api.github.com/repos/GLEECBTC/coins/contents/coins?ref={NEW}")
            self.assertEqual(request.call_args.kwargs["headers"]["Accept"], "application/vnd.github.raw+json")
            self.assertIs(request.call_args.kwargs["expected_type"], list)

    def test_get_coins_rejects_malformed_data_instead_of_reporting_removals(self):
        for data in ({"error": "Not found"}, [None], [{}], [{"coin": ""}],
                     [{"coin": 10}], [{"coin": "BTC\nInjected text"}]):
            with self.subTest(data=data), patch.object(monitor, "request_json", return_value=data):
                with self.assertRaises(monitor.MonitorError):
                    monitor.get_coins(self.cfg, NEW)

    def test_json_request_can_read_raw_array_but_default_requires_object(self):
        data = [{"coin": "BTC"}]
        with patch.object(monitor.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertEqual(monitor.request_json("https://example.test/coins", 1, "Test", expected_type=list), data)
        with patch.object(monitor.urllib.request, "urlopen", return_value=io.BytesIO(b"[]")):
            with self.assertRaises(monitor.MonitorError):
                monitor.request_json("https://example.test/coins", 1, "Test")

    def test_invalid_snapshot_state_is_rejected(self):
        for snapshots in (None, {"master": ["BTC"]}, {OLD: ["BTC", "BTC"]}, {OLD: [123]}):
            self.baseline()
            state = self.state()
            state["coins_by_commit"] = snapshots
            monitor.save_state(self.state_path, state)
            with self.subTest(snapshots=snapshots), self.assertRaises(monitor.MonitorError):
                self.state()

    def test_metadata_only_change_reports_no_additions_or_removals_but_restarts(self):
        self.baseline()
        with self.external() as (_, restart, telegram), \
                patch.object(monitor, "get_coins", return_value=COINS[OLD]):
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            restart.assert_called_once()
            message = telegram.call_args.args[1]
            self.assertIn("Added coins (0):\nNone", message)
            self.assertIn("Removed coins (0):\nNone", message)

    def test_empty_coin_array_is_a_valid_removal_of_all_coins(self):
        self.baseline()
        with self.external() as (_, _, telegram), patch.object(monitor, "get_coins", return_value=[]):
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            self.assertIn("Removed coins (3):\n- BTC\n- LTC\n- OLDCOIN", telegram.call_args.args[1])
        self.assertEqual(self.state()["coins_by_commit"][NEW], [])

    def test_long_diff_delivers_every_coin_and_retries_only_unsent_parts(self):
        self.baseline()
        many_coins = [f"TOKEN{i:04d}-BASE" for i in range(1000)]
        with self.external() as (_, restart, telegram), patch.object(monitor, "get_coins", return_value=many_coins):
            telegram.side_effect = [None, monitor.MonitorError("Telegram unavailable.")]
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 1)
            first_sent = telegram.call_args_list[0].args[1]
            remaining = self.state()["pending"][:]
            self.assertGreater(len(remaining), 1)
            self.assertIn("part 1/", first_sent)
            self.assertIn("part 2/", remaining[0])
            combined = first_sent + "".join(remaining)
            for coin in many_coins:
                self.assertEqual(combined.count("+ " + coin + "\n"), 1)
            for part in [first_sent, *remaining]:
                self.assertLessEqual(len(part.encode("utf-16-le")) // 2, 4096)
            telegram.reset_mock(side_effect=True)
            self.assertEqual(monitor.run_check(self.cfg, self.state_path), 0)
            self.assertEqual([call.args[1] for call in telegram.call_args_list], remaining)
            restart.assert_called_once()
        self.assertEqual(self.state()["pending"], [])

    def test_split_message_preserves_long_lines_and_unicode(self):
        message = "Header\n" + "\U0001f680" * 5000 + "\nFooter"
        parts = monitor.split_message(message)
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(part.split("\n", 1)[1] for part in parts), message)
        self.assertTrue(all(len(part.encode("utf-16-le")) // 2 <= 4096 for part in parts))


if __name__ == "__main__":
    unittest.main()
