"""bin/cx — Codex accounts. Runs in a temp HOME; network, processes and sockets are blocked."""
import contextlib
import io
import json
import os
import subprocess
import unittest
from unittest import mock

from helpers import SafeTestCase, codex_auth, load_tool

ALICE = codex_auth("alice@example.com", "user-alice", "acct-alice")
BOB = codex_auth("bob@example.com", "user-bob", "acct-bob", plan="prolite")


class CxTestCase(SafeTestCase):
    def setUp(self):
        super().setUp()
        self.cx = load_tool("cx")
        # Daemon, other apps and usage are faked: no process, socket or network.
        os.environ.pop("AI_USAGE_APP", None)  # run as from a terminal unless a test says otherwise
        self.restarts = []
        self.stops = []
        self.stop_result = True  # what stop_daemon reports: True stopped, False still running, None not running
        self.daemon = None
        for name, fake in (
            ("restart_daemon", lambda: self.restarts.append(True) or True),
            ("stop_daemon", lambda: self.stops.append(True) or self.stop_result),
            ("daemon_email", lambda: self.daemon),
            ("other_codex_hosts", lambda: []),
            ("fetch_usage", lambda auth: {"rate_limit": {}}),
        ):
            patcher = mock.patch.object(self.cx, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sign_in(self, auth):
        """What `codex login` leaves behind."""
        self.write_json(auth, ".codex", "auth.json")

    def save(self, name, auth):
        self.write_json(auth, ".codex-accounts", f"{name}.json")

    def stored(self, name):
        return self.read_json(".codex-accounts", f"{name}.json")

    def run_cx(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                self.cx.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class NamesTest(CxTestCase):
    def test_valid_names(self):
        for name in ("work", "alice.b", "a_b-c", "A1"):
            self.assertEqual(self.cx.valid_name(name), name)

    def test_rejected_names(self):
        for name in ("../x", "a/b", 'a"b', "a'b", "a b", 'x" -s "y', "abc\n", "", "-x", "rm", "json", "x" * 42):
            with self.assertRaises(SystemExit, msg=repr(name)), contextlib.redirect_stderr(io.StringIO()):
                self.cx.valid_name(name)

    def test_default_name_from_email(self):
        self.assertEqual(self.cx.default_name("john.doe+work@example.com"), "john.doe-work")
        self.assertEqual(self.cx.default_name("help@example.com"), "account")  # a command
        self.assertEqual(self.cx.default_name(None), "account")


class IdentityTest(CxTestCase):
    def test_chatgpt_account(self):
        email, plan, key = self.cx.identity(ALICE)
        self.assertEqual((email, plan, key), ("alice@example.com", "pro", ("user-alice", "acct-alice")))

    def test_api_key_sign_in_has_no_account(self):
        email, plan, key = self.cx.identity({"OPENAI_API_KEY": "sk-test-1234567890", "tokens": None})
        self.assertEqual((email, plan), ("API key", "api"))
        self.assertEqual(key, ("api-key", "34567890"))


class SyncActiveTest(CxTestCase):
    def test_copies_refreshed_tokens_to_the_matching_account_only(self):
        self.save("alice", ALICE)
        self.save("bob", BOB)
        refreshed = codex_auth("alice@example.com", "user-alice", "acct-alice", refresh="r2")
        self.sign_in(refreshed)
        self.assertEqual(self.cx.sync_active(), "alice")
        self.assertEqual(self.stored("alice"), refreshed)
        self.assertEqual(self.stored("bob"), BOB)

    def test_unsaved_active_account_touches_nothing(self):
        self.save("bob", BOB)
        self.sign_in(ALICE)
        self.assertIsNone(self.cx.sync_active())
        self.assertEqual(self.stored("bob"), BOB)

    def test_no_write_when_unchanged(self):
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        before = os.stat(self.path(".codex-accounts", "alice.json")).st_mtime_ns
        with mock.patch.object(self.cx, "write_private") as write:
            self.cx.sync_active()
        write.assert_not_called()
        self.assertEqual(os.stat(self.path(".codex-accounts", "alice.json")).st_mtime_ns, before)


class SaveTest(CxTestCase):
    def test_save_with_default_name(self):
        self.sign_in(ALICE)
        code, _ = self.run_cx("save")
        self.assertEqual(code, 0)
        self.assertEqual(self.stored("alice"), ALICE)
        self.assertEqual(os.stat(self.path(".codex-accounts", "alice.json")).st_mode & 0o777, 0o600)

    def test_refuses_to_overwrite_another_account(self):
        self.save("alice", ALICE)
        self.sign_in(codex_auth("alice@example.org", "user-other", "acct-other"))  # same default name
        code, out = self.run_cx("save")
        self.assertEqual(code, 1)
        self.assertIn("another account", out)
        self.assertEqual(self.stored("alice"), ALICE)

    def test_refuses_to_save_the_same_account_twice(self):
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        code, out = self.run_cx("save", "again")
        self.assertEqual(code, 1)
        self.assertIn('already saved as "alice"', out)
        self.assertFalse(os.path.exists(self.path(".codex-accounts", "again.json")))


class UseTest(CxTestCase):
    def test_switch_writes_auth_and_keeps_refreshed_tokens(self):
        self.save("alice", ALICE)
        self.save("bob", BOB)
        refreshed = codex_auth("alice@example.com", "user-alice", "acct-alice", refresh="r2")
        self.sign_in(refreshed)
        self.daemon = "bob@example.com"
        code, out = self.run_cx("use", "bob")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read_json(".codex", "auth.json"), BOB)
        self.assertEqual(self.stored("alice"), refreshed)
        self.assertEqual(self.restarts, [True])
        self.assertIn("restarted and verified", out)

    def test_unsaved_active_account_is_backed_up(self):
        self.save("bob", BOB)
        self.sign_in(ALICE)
        code, _ = self.run_cx("use", "bob")
        self.assertEqual(code, 0)
        backups = [f for f in os.listdir(self.path(".codex-accounts")) if f.startswith("_backup-")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.read_json(".codex-accounts", backups[0]), ALICE)

    def test_already_active(self):
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        code, out = self.run_cx("use", "alice")
        self.assertEqual(code, 0)
        self.assertIn("Already on", out)
        self.assertEqual(self.restarts, [])

    def test_note_lists_apps_to_restart(self):
        self.save("bob", BOB)
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        with mock.patch.object(self.cx, "other_codex_hosts", lambda: ["ChatGPT", "Cursor"]):
            _, out = self.run_cx("use", "bob")
        self.assertIn("NOTE: Restart ChatGPT and Cursor to use this account there.", out)

    def test_legacy_name_still_usable_and_removable(self):
        self.save("john.doe+work", BOB)
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        self.assertEqual(self.run_cx("use", "john.doe+work")[0], 0)
        self.assertEqual(self.read_json(".codex", "auth.json"), BOB)
        self.assertEqual(self.run_cx("use", "alice")[0], 0)
        self.assertEqual(self.run_cx("rm", "john.doe+work")[0], 0)
        self.assertFalse(os.path.exists(self.path(".codex-accounts", "john.doe+work.json")))

    def test_invalid_name_never_creates_a_file(self):
        self.sign_in(ALICE)
        self.assertEqual(self.run_cx("save", "../escape")[0], 1)
        self.assertFalse(os.path.exists(self.path("escape.json")))


class UseFromAppTest(CxTestCase):
    """Run by the app, cx stops the daemon instead of restarting it (a daemon it starts would be
    attributed to the app by macOS); codex starts it again by itself."""

    def setUp(self):
        super().setUp()
        os.environ["AI_USAGE_APP"] = "1"
        self.save("alice", ALICE)
        self.save("bob", BOB)
        self.sign_in(ALICE)

    def test_switch_stops_the_daemon_instead_of_restarting_it(self):
        code, out = self.run_cx("use", "bob")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read_json(".codex", "auth.json"), BOB)
        self.assertEqual((self.stops, self.restarts), ([True], []))
        self.assertIn("Codex daemon stopped: the next codex session starts it on this account.", out)

    def test_daemon_still_running_is_the_first_note(self):
        self.stop_result = False
        with mock.patch.object(self.cx, "other_codex_hosts", lambda: ["ChatGPT"]):
            _, out = self.run_cx("use", "bob")
        notes = [line for line in out.splitlines() if line.startswith("NOTE: ")]
        self.assertEqual(notes, [
            "NOTE: The Codex daemon is still running on the previous account: "
            "run codex app-server daemon restart in a terminal.",
            "NOTE: Restart ChatGPT to use this account there.",
        ])
        self.assertNotIn("daemon stopped", out)

    def test_no_daemon_running_says_nothing_about_it(self):
        self.stop_result = None
        code, out = self.run_cx("use", "bob")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stops, [True])
        self.assertNotIn("daemon", out)
        self.assertNotIn("NOTE", out)

    def test_already_on_with_daemon_on_the_old_account_stops_it(self):
        self.daemon = "bob@example.com"
        code, out = self.run_cx("use", "alice")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.stops, self.restarts), ([True], []))
        self.assertIn("daemon was still on bob@example.com", out)

    def test_other_values_keep_the_terminal_behavior(self):
        for value in ("0", "", "true"):
            os.environ["AI_USAGE_APP"] = value
            self.stops.clear()
            self.restarts.clear()
            self.sign_in(ALICE)
            self.daemon = "bob@example.com"
            self.assertEqual(self.run_cx("use", "bob")[0], 0)
            self.assertEqual((self.stops, self.restarts), ([], [True]), value)


class DaemonCommandsTest(SafeTestCase):
    """The codex commands behind restart_daemon / stop_daemon, with subprocess.run faked."""

    RUNNING = '{"status":"running","backend":"pid"}'
    NOT_RUNNING = '{"status":"notRunning"}'

    def setUp(self):
        super().setUp()
        self.cx = load_tool("cx")
        self.calls = []
        self.versions = []  # successive `daemon version` results: stdout, (stdout, exit code) or an Exception to raise
        patcher = mock.patch.object(self.cx, "codex_bin", lambda: "/fake/codex")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(self.cx.subprocess, "run", self.fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_run(self, args, **kwargs):
        self.assertEqual(args[:3], ["/fake/codex", "app-server", "daemon"])
        self.calls.append(args[3])
        out, code = "", 0
        if args[3] == "version":
            out = self.versions.pop(0)
            if isinstance(out, Exception):
                raise out
            if isinstance(out, tuple):
                out, code = out
        return subprocess.CompletedProcess(args, code, out, "")

    def test_stop_then_verified(self):
        self.versions = [self.RUNNING, self.NOT_RUNNING]
        self.assertIs(self.cx.stop_daemon(), True)
        self.assertEqual(self.calls, ["version", "stop", "version"])

    def test_stop_that_leaves_it_running(self):
        self.versions = [self.RUNNING, self.RUNNING]
        self.assertIs(self.cx.stop_daemon(), False)
        self.assertEqual(self.calls, ["version", "stop", "version"])

    def test_stop_unverifiable_is_not_reported_as_stopped(self):
        self.versions = [self.RUNNING, subprocess.TimeoutExpired("codex", 15)]
        self.assertIs(self.cx.stop_daemon(), False)

    def test_stop_with_a_failed_check_is_not_reported_as_stopped(self):
        for after in (("", 1), ("error: no daemon socket", 1), ('{"status":"weird"}', 0)):
            self.calls.clear()
            self.versions = [self.RUNNING, after]
            self.assertIs(self.cx.stop_daemon(), False, after)
            self.assertEqual(self.calls, ["version", "stop", "version"])

    def test_stop_when_not_running_does_nothing(self):
        self.versions = [self.NOT_RUNNING]
        self.assertIsNone(self.cx.stop_daemon())
        self.assertEqual(self.calls, ["version"])

    def test_restart_unchanged(self):
        self.versions = [self.RUNNING]
        self.assertIs(self.cx.restart_daemon(), True)
        self.assertEqual(self.calls, ["version", "restart"])
        self.calls.clear()
        for version in (self.NOT_RUNNING, subprocess.TimeoutExpired("codex", 15), ("", 1)):
            self.calls.clear()
            self.versions = [version]
            self.assertIs(self.cx.restart_daemon(), False, version)
            self.assertEqual(self.calls, ["version"])

    def test_without_codex_nothing_runs(self):
        with mock.patch.object(self.cx, "codex_bin", lambda: None):
            self.assertIsNone(self.cx.stop_daemon())
            self.assertIs(self.cx.restart_daemon(), False)
        self.assertEqual(self.calls, [])


class RemoveTest(CxTestCase):
    def test_refuses_to_remove_the_active_account(self):
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        code, out = self.run_cx("rm", "alice")
        self.assertEqual(code, 1)
        self.assertIn("active account", out)
        self.assertTrue(os.path.exists(self.path(".codex-accounts", "alice.json")))


class ReadOnlyCommandsTest(CxTestCase):
    def test_listing_without_store_creates_nothing(self):
        for argv in ([], ["json"]):
            code, out = self.run_cx(*argv)
            self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.run_cx("json")[1]), [])
        self.assertFalse(os.path.exists(self.path(".codex-accounts")))


if __name__ == "__main__":
    unittest.main()
