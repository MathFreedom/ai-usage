"""bin/cx — Codex accounts. Runs in a temp HOME; network, processes and sockets are blocked."""
import contextlib
import errno
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

    def test_malformed_window_in_the_file_is_dropped(self):
        bad = dict(self.WEEK, used_percent=float("nan"))
        entry = {"key": ["user-alice", "acct-alice"], "at": 1.0, "resets": [],
                 "rate_limit": {"primary_window": bad, "secondary_window": self.WEEK}}
        with open(self.path(".codex-accounts", "_usage.json"), "w") as f:
            json.dump({"alice": entry}, f)  # NaN written as JSON's NaN, as a hand edit could
        code, out = self.run_cx("json")
        self.assertEqual(code, 0, out)
        alice = json.loads(out, parse_constant=self.fail)[0]  # no NaN printed
        self.assertEqual((alice["windows"], alice["last_seen"]), ([self.WEEK], 1.0))
        self.assertEqual(self.run_cx()[0], 0)
        for bad in (dict(self.WEEK, reset_at=10 ** 400), dict(self.WEEK, extra={"x": [float("nan")]})):
            entry["rate_limit"]["primary_window"] = bad
            with open(self.path(".codex-accounts", "_usage.json"), "w") as f:
                json.dump({"alice": entry}, f)
            self.assertEqual(json.loads(self.run_cx("json")[1], parse_constant=self.fail)[0]["windows"], [self.WEEK])

    def test_deeply_nested_window_in_the_file(self):
        entry = {"key": ["user-alice", "acct-alice"], "at": 1.0, "resets": [], "rate_limit": {}}
        with open(self.path(".codex-accounts", "_usage.json"), "w") as f:
            f.write(json.dumps({"alice": entry})[:-4] + '{"primary_window": {"used_percent": 1, "extra": %s}, '
                    '"secondary_window": %s}}}' % ("[" * 600 + "NaN" + "]" * 600, json.dumps(self.WEEK)))
        with open(self.path(".codex-accounts", "_usage.json")) as f:
            json.load(f)  # the file itself is valid JSON
        code, out = self.run_cx("json")
        self.assertEqual(code, 0, out[-300:])
        alice = json.loads(out, parse_constant=self.fail)[0]
        self.assertEqual((alice["windows"], alice["last_seen"]), ([self.WEEK], 1.0))
        self.assertEqual(self.run_cx()[0], 0)

    def test_list_with_a_null_reset_time(self):
        self.usage["alice@example.com"] = {"rate_limit": {"primary_window": dict(self.WEEK, reset_at=None)}}
        code, out = self.run_cx()
        self.assertEqual(code, 0, out)
        self.assertIn("42%", out)

    def test_failed_write_still_shows_the_usage(self):
        self.usage["alice@example.com"] = self.LIVE
        with mock.patch.object(self.cx, "write_private", side_effect=PermissionError("read-only")):
            self.assertEqual(self.accounts_json()["alice"]["windows"], [self.WEEK])
        os.mkdir(self.path(".codex-accounts", "_usage.json"))  # can't be replaced by a file
        for _ in range(2):
            self.assertEqual(self.accounts_json()["alice"]["windows"], [self.WEEK])
        self.assertEqual([f for f in os.listdir(self.path(".codex-accounts")) if f.startswith(".cx-")], [])

    def test_failed_write_leaves_no_temp_and_raises(self):
        target = self.path(".codex-accounts", "alice.json")
        before = self.stored("alice")
        for error in (OSError("disk full"), KeyboardInterrupt()):
            with mock.patch.object(self.cx.os, "replace", side_effect=error), self.assertRaises(type(error)):
                self.cx.write_private(target, {"x": 1})
            self.assertEqual(self.stored("alice"), before)
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

    WEEK = {"used_percent": 42, "limit_window_seconds": 604800, "reset_at": 2000000000}

    def fetch(self, usage, credits='{"credits": []}'):
        """fetch_usage with the usage endpoint answering `usage` (a JSON text, NaN allowed)."""
        bodies = {self.cx.USAGE_URL: usage, self.cx.RESETS_URL: credits}
        urlopen = lambda req, timeout=None: io.BytesIO(bodies[req.full_url].encode())
        with mock.patch.object(self.cx.urllib.request, "urlopen", urlopen):
            return self.cx.fetch_usage(ALICE)

    def test_non_object_response_is_unreachable(self):
        for body in ("[]", "null", "5", '"x"'):
            self.assertEqual(self.fetch(body), {"error": "usage unreachable"}, body)

    def test_malformed_window_is_dropped(self):
        for field in ("used_percent", "limit_window_seconds", "reset_at"):
            for bad in ('"x"', "NaN", "Infinity", "-Infinity", "true", "[]", "1" + "0" * 400, "1e12", "-1e12"):
                fields = dict({k: json.dumps(v) for k, v in self.WEEK.items()}, **{field: bad})
                window = "{" + ", ".join(f'"{k}": {v}' for k, v in fields.items()) + "}"
                body = '{"rate_limit": {"primary_window": %s, "secondary_window": %s}}' % (window, json.dumps(self.WEEK))
                rl = self.fetch(body)["rate_limit"]
                self.assertEqual((rl["primary_window"], rl["secondary_window"]), (None, self.WEEK), (field, bad))
        for window in ('"x"', "[]", "5"):
            self.assertIsNone(self.fetch('{"rate_limit": {"primary_window": %s}}' % window)["rate_limit"]["primary_window"])
        for extra in ("NaN", "1" + "0" * 400, "1000000000000", '{"x": NaN}', "[Infinity]", '[{"x": %s}]' % ("1" + "0" * 400)):
            body = '{"rate_limit": {"primary_window": {"used_percent": 1, "reset_after_seconds": %s}}}' % extra
            self.assertIsNone(self.fetch(body)["rate_limit"]["primary_window"], extra)  # any number, nested too
        kept = dict(self.WEEK, reset_after_seconds=60, note="x", flag=True, extra={"b": [False]})
        self.assertEqual(self.fetch(json.dumps({"rate_limit": {"primary_window": kept}}))["rate_limit"]["primary_window"], kept)
        nulls = dict(self.WEEK, limit_window_seconds=None, reset_at=None)
        self.assertEqual(self.fetch(json.dumps({"rate_limit": {"primary_window": nulls}}))["rate_limit"]["primary_window"], nulls)

    def test_sane_walks_any_depth(self):
        for bottom, ok in ((1, True), (float("nan"), False)):
            v = bottom
            for _ in range(100000):  # far deeper than any recursion would go
                v = [{"a": v}]
            self.assertIs(self.cx.sane(v), ok)
        for v, ok in (([1, float("nan")], False), ([float("nan"), 1], False), ({"a": float("nan"), "b": 1}, False),
                      ({"a": 1, "b": float("inf")}, False), ([1, {"a": [2, True, "x", None]}], True)):
            self.assertIs(self.cx.sane(v), ok, v)

    def test_deeply_nested_window(self):
        for bottom, kept in (("1", True), ("NaN", False)):
            nested = "[" * 600 + bottom + "]" * 600  # past a two-frames-per-level recursion, within json.load's
            body = '{"rate_limit": {"primary_window": {"used_percent": 1, "extra": %s}}}' % nested
            window = self.fetch(body)["rate_limit"]["primary_window"]
            self.assertEqual(window is not None, kept, bottom)

    def test_rate_limit_not_an_object(self):
        for rl in ('"x"', "5", "[]", "null", "true"):
            self.assertEqual(self.fetch('{"rate_limit": %s}' % rl)["rate_limit"],
                             {"primary_window": None, "secondary_window": None}, rl)
        self.assertNotIn("rate_limit", self.fetch('{"plan_type": "free"}'))  # no limits: left as the API says

    def test_malformed_credits_are_ignored(self):
        credit = {"status": "available", "is_supported_by_plan": True, "expires_at": "2099-01-01T00:00:00Z"}
        credits = json.dumps({"credits": [5, "x", dict(credit, expires_at=5), dict(credit, expires_at=None),
                                          dict(credit, expires_at=""), credit]})
        self.assertEqual(self.fetch(json.dumps({"rate_limit": {}}), credits)["_resets"], ["2099-01-01T00:00:00Z"])


class MalformedAccountTest(SafeTestCase):
    """One account's malformed usage leaves the others listed."""

    def test_other_accounts_still_listed(self):
        cx = load_tool("cx")
        bob = codex_auth("bob@example.com", "user-bob", "acct-bob")
        for name, auth in (("alice", ALICE), ("bob", bob)):
            self.write_json(auth, ".codex-accounts", f"{name}.json")
        self.write_json(ALICE, ".codex", "auth.json")
        week = {"used_percent": 42, "limit_window_seconds": 604800, "reset_at": 2000000000}

        def urlopen(req, timeout=None):
            if req.full_url == cx.RESETS_URL:
                return io.BytesIO(b'{"credits": []}')
            if req.get_header("Chatgpt-account-id") == "acct-alice":
                return io.BytesIO(b'{"rate_limit": {"primary_window": {"used_percent": NaN}}}')
            return io.BytesIO(json.dumps({"rate_limit": {"primary_window": week}}).encode())

        with mock.patch.object(cx.urllib.request, "urlopen", urlopen):
            for argv in (["json"], []):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cx.main(argv)
                if argv:
                    rows = {a["name"]: a for a in json.loads(out.getvalue(), parse_constant=self.fail)}
                    self.assertEqual((rows["alice"]["windows"], rows["bob"]["windows"]), ([], [week]))
                else:
                    self.assertIn("42%", out.getvalue())


class LockTest(CxTestCase):
    def setUp(self):
        super().setUp()
        self.save("alice", ALICE)
        self.sign_in(ALICE)
        self.flocks = []
        patcher = mock.patch.object(self.cx.fcntl, "flock", lambda fd, op: self.flocks.append(op))
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_only_store(self):
        os.chmod(self.path(".codex-accounts"), 0o500)
        self.addCleanup(os.chmod, self.path(".codex-accounts"), 0o700)

    def test_commands_hold_the_lock(self):
        self.addCleanup(os.umask, os.umask(0))  # the mode below is cx's own, not the umask's
        for argv in (["json"], [], ["save", "alice"]):
            self.flocks.clear()
            self.assertEqual(self.run_cx(*argv)[0], 0, argv)
            self.assertEqual(self.flocks, [self.cx.fcntl.LOCK_EX], argv)
        self.assertEqual(os.stat(self.path(".codex-accounts", ".lock")).st_mode & 0o777, 0o600)

    def test_lock_that_cant_be_created_in_a_writable_store(self):
        real_open = os.open

        def full_disk(path, *args):
            if path.endswith(".lock"):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(path, *args)

        with mock.patch.object(self.cx.os, "open", full_disk), self.assertRaises(OSError):
            self.run_cx("json")
        self.assertEqual(self.flocks, [])

    def test_read_only_lock_file_still_locks(self):
        lock = self.path(".codex-accounts", ".lock")
        open(lock, "w").close()
        os.chmod(lock, 0o444)
        self.assertEqual(self.run_cx("json")[0], 0)
        self.assertEqual(self.flocks, [self.cx.fcntl.LOCK_EX])

    def test_unreadable_lock_is_an_error(self):
        lock = self.path(".codex-accounts", ".lock")
        open(lock, "w").close()
        os.chmod(lock, 0o000)
        self.addCleanup(os.chmod, lock, 0o600)
        with self.assertRaises(PermissionError):  # never a silent unlocked run in a writable store
            self.run_cx("json")
        self.read_only_store()
        with self.assertRaises(PermissionError):  # nor when the lock exists in a read-only one
            self.run_cx("json")
        self.assertEqual(self.flocks, [])

    def test_dangling_lock_link_in_a_read_only_store(self):
        os.symlink("missing", self.path(".codex-accounts", ".lock"))  # target can't be created there
        self.read_only_store()
        with self.assertRaises(OSError):
            self.run_cx("json")
        self.assertEqual(self.flocks, [])

    def test_listing_works_in_a_read_only_store(self):
        self.read_only_store()
        for argv in (["json"], []):
            code, out = self.run_cx(*argv)
            self.assertEqual(code, 0, out)
        self.assertEqual(self.flocks, [])
        self.assertFalse(os.path.exists(self.path(".codex-accounts", ".lock")))

    def test_rotated_tokens_in_a_read_only_store(self):
        rotated = codex_auth("alice@example.com", "user-alice", "acct-alice", refresh="r2")
        self.sign_in(rotated)
        self.read_only_store()
        code, out = self.run_cx("json")
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)[0]["active"])
        with self.assertRaises(PermissionError):  # a switch must not go on without saving them
            self.cx.sync_active()
        self.assertEqual(self.stored("alice"), ALICE)


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
