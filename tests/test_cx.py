"""bin/cx — Codex accounts. Runs in a temp HOME; network, processes and sockets are blocked."""
import contextlib
import io
import json
import os
import subprocess
import unittest
import urllib.error
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
        for value in ("0", "", "true", " 1"):
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
    GONE = ("", 1)  # what codex 0.162 `daemon version` gives once no daemon runs: it can't connect
    # `daemon version` answers that don't say "running": no daemon to stop or restart
    CANT_TELL = (GONE, NOT_RUNNING, '{"status":"starting"}', '{"status":"weird"}',
                 'error: "running" state unknown',
                 subprocess.TimeoutExpired("codex", 15))

    def setUp(self):
        super().setUp()
        self.cx = load_tool("cx")
        self.calls = []
        # Successive `daemon version` results, and the `daemon stop` result: stdout,
        # (stdout, exit code) or an Exception to raise.
        self.versions = []
        self.stop = '{"status":"stopped"}'
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
        if args[3] in ("version", "stop"):
            out = self.versions.pop(0) if args[3] == "version" else self.stop
            if isinstance(out, Exception):
                raise out
            if isinstance(out, tuple):
                out, code = out
        return subprocess.CompletedProcess(args, code, out, "")

    def test_stop_reported_and_daemon_gone(self):
        for stop in ('{"status":"stopped"}', '{"status":"notRunning"}'):
            for after in (self.GONE, self.NOT_RUNNING, subprocess.TimeoutExpired("codex", 15)):
                self.calls.clear()
                self.versions = [self.RUNNING, after]
                self.stop = stop
                self.assertIs(self.cx.stop_daemon(), True, (stop, after))
                self.assertEqual(self.calls, ["version", "stop", "version"])

    def test_stop_that_leaves_it_running(self):
        self.versions = [self.RUNNING, self.RUNNING]
        self.assertIs(self.cx.stop_daemon(), False)
        self.assertEqual(self.calls, ["version", "stop", "version"])

    def test_stop_not_confirmed_is_not_reported_as_stopped(self):
        for stop in (("", 1), ("error: permission denied", 1), '{"status":"running"}', '{"status":"weird"}',
                     subprocess.TimeoutExpired("codex", 60)):
            self.calls.clear()
            self.versions = [self.RUNNING]
            self.stop = stop
            self.assertIs(self.cx.stop_daemon(), False, stop)
            self.assertEqual(self.calls, ["version", "stop"])

    def test_stop_when_not_running_does_nothing(self):
        for version in self.CANT_TELL:
            self.calls.clear()
            self.versions = [version]
            self.assertIsNone(self.cx.stop_daemon(), version)
            self.assertEqual(self.calls, ["version"])

    def test_restart_unchanged(self):
        self.versions = [self.RUNNING]
        self.assertIs(self.cx.restart_daemon(), True)
        self.assertEqual(self.calls, ["version", "restart"])
        self.calls.clear()
        for version in self.CANT_TELL:
            self.calls.clear()
            self.versions = [version]
            self.assertIs(self.cx.restart_daemon(), False, version)
            self.assertEqual(self.calls, ["version"])

    def test_without_codex_nothing_runs(self):
        with mock.patch.object(self.cx, "codex_bin", lambda: None):
            self.assertIsNone(self.cx.stop_daemon())
            self.assertIs(self.cx.restart_daemon(), False)
        self.assertEqual(self.calls, [])


class LastKnownUsageTest(CxTestCase):
    """_usage.json: the last usage read per account, returned when it can't be read."""

    WEEK = {"used_percent": 42, "limit_window_seconds": 604800, "reset_at": 2000000000}
    LIVE = {"rate_limit": {"limit_reached": True, "primary_window": WEEK},
            "_resets": ["2000-01-01T00:00:00.123Z", "2099-01-01T00:00:00.5Z"]}

    def setUp(self):
        super().setUp()
        self.usage = {}  # email -> fetch_usage response; missing = unreachable
        patcher = mock.patch.object(self.cx, "fetch_usage", lambda auth: self.usage.get(
            self.cx.identity(auth)[0], {"error": "usage unreachable"}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.save("alice", ALICE)
        self.sign_in(ALICE)

    def cache(self):
        return self.read_json(".codex-accounts", "_usage.json")

    def accounts_json(self):
        code, out = self.run_cx("json")
        self.assertEqual(code, 0, out)
        return {a["name"]: a for a in json.loads(out)}

    def test_last_reading_returned_when_unreachable(self):
        self.usage["alice@example.com"] = self.LIVE
        live = self.accounts_json()["alice"]
        self.assertIsNone(live["last_seen"])
        self.assertEqual(os.stat(self.path(".codex-accounts", "_usage.json")).st_mode & 0o777, 0o600)
        read_at = self.cache()["alice"]["at"]
        del self.usage["alice@example.com"]
        last = self.accounts_json()["alice"]
        self.assertEqual(last["error"], "usage unreachable")
        self.assertEqual(last["windows"], [self.WEEK])
        self.assertTrue(last["limit_reached"])
        self.assertEqual(last["last_seen"], read_at)
        self.assertEqual(last["resets"], ["2099-01-01T00:00:00.5Z"])  # the expired one is dropped

    def test_any_failure_falls_back(self):
        self.usage["alice@example.com"] = self.LIVE
        self.accounts_json()
        for error in ("HTTP 401", "token expired (cx use refreshes it)"):
            self.usage["alice@example.com"] = {"error": error}
            last = self.accounts_json()["alice"]
            self.assertEqual((last["error"], last["windows"]), (error, [self.WEEK]))

    def test_reading_of_another_login_is_ignored(self):
        self.usage["alice@example.com"] = self.LIVE
        self.accounts_json()
        other = codex_auth("alice@example.com", "user-alice", "acct-team")  # same name, other workspace
        self.save("alice", other)
        self.sign_in(other)
        del self.usage["alice@example.com"]
        last = self.accounts_json()["alice"]
        self.assertEqual((last["windows"], last["resets"], last["last_seen"]), ([], [], None))

    def test_removed_account_leaves_the_file(self):
        self.save("bob", BOB)
        self.usage = {"alice@example.com": self.LIVE, "bob@example.com": self.LIVE}
        self.accounts_json()
        self.assertEqual(sorted(self.cache()), ["alice", "bob"])
        self.assertEqual(self.run_cx("rm", "bob")[0], 0)
        self.accounts_json()
        self.assertEqual(sorted(self.cache()), ["alice"])

    def test_not_rewritten_while_unreachable(self):
        self.assertEqual(self.accounts_json()["alice"]["windows"], [])  # nothing kept yet: as before
        self.assertFalse(os.path.exists(self.path(".codex-accounts", "_usage.json")))
        self.usage["alice@example.com"] = self.LIVE
        self.accounts_json()
        del self.usage["alice@example.com"]
        with mock.patch.object(self.cx, "write_private") as write:
            self.accounts_json()
            self.run_cx()
        write.assert_not_called()

    def test_unreadable_file_is_replaced(self):
        key = ["user-alice", "acct-alice"]
        entry = {"key": key, "at": 1.0, "rate_limit": {"primary_window": self.WEEK}, "resets": []}
        bad = ["{not json", "[]", "null", '{"alice": 5}'] + [json.dumps({"alice": dict(entry, **change)}) for change in (
            {"rate_limit": "x"}, {"rate_limit": {"primary_window": "x"}},
            {"rate_limit": {"primary_window": self.WEEK, "secondary_window": "x"}}, {"resets": 5},
            {"resets": [5, None]}, {"at": "yesterday"}, {"at": None}, {"at": True}, {"at": float("nan")},
            {"at": float("inf")}, {"at": 1e300}, {"at": -1})]
        for content in bad:
            with open(self.path(".codex-accounts", "_usage.json"), "w") as f:
                f.write(content)
            self.usage.pop("alice@example.com", None)
            for argv in (["json"], []):
                code, out = self.run_cx(*argv)
                self.assertEqual(code, 0, (content, out))
            ignored = self.accounts_json()["alice"]
            self.assertEqual((ignored["windows"], ignored["last_seen"]), ([], None), content)
            self.usage["alice@example.com"] = self.LIVE
            self.accounts_json()
            self.assertEqual(self.cache()["alice"]["rate_limit"], self.LIVE["rate_limit"], content)

    def test_failed_write_still_shows_the_usage(self):
        self.usage["alice@example.com"] = self.LIVE
        with mock.patch.object(self.cx, "write_private", side_effect=PermissionError("read-only")):
            self.assertEqual(self.accounts_json()["alice"]["windows"], [self.WEEK])
        os.mkdir(self.path(".codex-accounts", "_usage.json"))  # can't be replaced by a file
        for _ in range(2):
            self.assertEqual(self.accounts_json()["alice"]["windows"], [self.WEEK])
        self.assertEqual([f for f in os.listdir(self.path(".codex-accounts")) if f.startswith(".cx-")], [])

    def test_reading_without_limits_is_kept(self):
        self.usage["alice@example.com"] = {"rate_limit": None, "_resets": ["2099-01-01T00:00:00Z", 5]}
        self.accounts_json()
        del self.usage["alice@example.com"]
        last = self.accounts_json()["alice"]
        self.assertIsNotNone(last["last_seen"])
        self.assertEqual((last["windows"], last["resets"]), ([], ["2099-01-01T00:00:00Z"]))
        self.assertIn("no limit", self.run_cx()[1])

    def test_list_shows_the_last_reading(self):
        self.usage["alice@example.com"] = self.LIVE
        self.accounts_json()
        del self.usage["alice@example.com"]
        code, out = self.run_cx()
        self.assertEqual(code, 0)
        self.assertIn("42%", out)
        self.assertIn("(last seen ", out)
        self.assertIn("usage unreachable", out)
        self.assertIn("1 free reset(s)", out)


class FetchUsageTest(SafeTestCase):
    def setUp(self):
        super().setUp()
        self.cx = load_tool("cx")

    def test_errors(self):
        http = urllib.error.HTTPError("https://chatgpt.com", 429, "Too Many Requests", {}, None)
        for raised, error in ((urllib.error.URLError("[Errno 61] Connection refused"), "usage unreachable"),
                              (TimeoutError("timed out"), "usage unreachable"), (http, "HTTP 429")):
            with mock.patch.object(self.cx.urllib.request, "urlopen", side_effect=raised):
                self.assertEqual(self.cx.fetch_usage(ALICE), {"error": error})


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
