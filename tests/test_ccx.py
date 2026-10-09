"""bin/ccx — Claude Code accounts. Runs in a temp HOME against an in-memory fake of macOS
`security`; the API is faked and real processes, network and sockets are blocked."""
import contextlib
import io
import json
import os
import time
import unittest
from unittest import mock

from helpers import FakeSecurity, RealCallBlocked, SafeTestCase, claude_account, claude_creds, load_tool

ACTIVE = "Claude Code-credentials"
ALICE_ACCOUNT = claude_account("uuid-alice", "alice@example.com")
BOB_ACCOUNT = claude_account("uuid-bob", "bob@example.com")


class CcxTestCase(SafeTestCase):
    def setUp(self):
        super().setUp()
        self.ccx = load_tool("ccx")
        self.keychain = FakeSecurity()

        def run(args, **kwargs):
            if args and args[0] == self.ccx.SECURITY:
                return self.keychain.run(args, **kwargs)
            raise RealCallBlocked(f"test reached a real process: {args[:1]}")

        self.tokens = {}  # access token -> (uuid, email): what /api/oauth/profile answers
        self.usage_calls = []

        def api_get(path, token):
            if path == "profile":
                uuid, email = self.tokens[token]
                return {"account": {"uuid": uuid, "email": email}}
            if path == "usage":
                self.usage_calls.append(token)
                return {"limits": [{"kind": "session", "percent": 12, "resets_at": "2099-01-01T00:00:00+00:00"},
                                   {"kind": "weekly_all", "percent": 3, "resets_at": "2099-01-07T00:00:00+00:00"}]}
            raise AssertionError(path)

        for patcher in (
            mock.patch("subprocess.run", run),
            mock.patch.object(self.ccx, "api_get", api_get),
            mock.patch.object(self.ccx, "claude_sessions", lambda: 0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    # Claude Code's own state

    def sign_in(self, creds, account, extra=None):
        """What Claude Code keeps: the Keychain item and oauthAccount in ~/.claude.json."""
        self.keychain.items[ACTIVE] = ("mathis", json.dumps(creds))
        token = creds["claudeAiOauth"]["accessToken"]
        self.tokens[token] = (account["accountUuid"], account["emailAddress"])
        config = {"numStartups": 7, "projects": {"/x": {}}, "oauthAccount": account}
        config.update(extra or {})
        self.write_json(config, ".claude.json")
        os.chmod(self.path(".claude.json"), 0o644)

    def active_creds(self):
        return json.loads(self.keychain.items[ACTIVE][1])

    def run_ccx(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                self.ccx.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class PackingTest(CcxTestCase):
    def test_round_trip(self):
        obj = {"credentials": claude_creds("tok"), "oauthAccount": ALICE_ACCOUNT}
        self.assertEqual(self.ccx.unpack(self.ccx.pack(obj)), obj)
        self.assertEqual(self.ccx.unpack(json.dumps(obj)), obj)  # plain JSON still readable

    def test_saved_entry_fits_in_one_security_line(self):
        self.sign_in(claude_creds("tok-a"), ALICE_ACCOUNT)
        self.assertEqual(self.run_ccx("save", "alice")[0], 0)
        self.assertIn("ai-usage-claude:alice", self.keychain.items)

    def test_secret_never_in_argv(self):
        self.sign_in(claude_creds("tok-secret-a"), ALICE_ACCOUNT)
        self.run_ccx("save", "alice")
        self.assertFalse(any("tok-secret-a" in " ".join(c) for c in self.keychain.commands))

    def test_oversized_write_is_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.ccx.kc_write("x", "y", "z" * 3000)
        self.assertNotIn("x", self.keychain.items)


class SaveTest(CcxTestCase):
    def test_save_with_default_name(self):
        self.sign_in(claude_creds("tok-a"), ALICE_ACCOUNT)
        code, out = self.run_ccx("save")
        self.assertEqual(code, 0, out)
        entry = self.ccx.stored("alice")
        self.assertEqual(entry["credentials"]["claudeAiOauth"]["accessToken"], "tok-a")
        self.assertEqual(entry["oauthAccount"], ALICE_ACCOUNT)
        meta = self.read_json(".config", "ai-usage", "claude-accounts.json")
        self.assertEqual(meta["alice"]["uuid"], "uuid-alice")
        self.assertNotIn("tok-a", json.dumps(meta))  # no secret in the metadata file

    def test_refuses_to_overwrite_another_account(self):
        self.sign_in(claude_creds("tok-a"), ALICE_ACCOUNT)
        self.run_ccx("save", "alice")
        self.sign_in(claude_creds("tok-other"), claude_account("uuid-other", "alice@example.org"))
        code, out = self.run_ccx("save")
        self.assertEqual(code, 1)
        self.assertIn("another account", out)
        self.assertEqual(self.ccx.stored("alice")["oauthAccount"], ALICE_ACCOUNT)


class UseTest(CcxTestCase):
    def setUp(self):
        super().setUp()
        self.bob_creds = claude_creds("tok-b", plan="pro")
        self.sign_in(self.bob_creds, BOB_ACCOUNT)
        self.run_ccx("save", "bob")
        self.sign_in(claude_creds("tok-a"), ALICE_ACCOUNT, extra={"theme": "dark"})
        self.run_ccx("save", "alice")

    def test_switch_swaps_the_keychain_item_and_only_oauth_account(self):
        code, out = self.run_ccx("use", "bob")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.active_creds(), self.bob_creds)
        config = self.read_json(".claude.json")
        self.assertEqual(config["oauthAccount"], BOB_ACCOUNT)
        self.assertEqual((config["numStartups"], config["theme"]), (7, "dark"))  # rest untouched
        self.assertEqual(os.stat(self.path(".claude.json")).st_mode & 0o777, 0o644)
        self.assertIn("(verified)", out)

    def test_refreshed_tokens_of_the_previous_account_are_kept(self):
        rotated = claude_creds("tok-a2", refresh="r2")
        self.keychain.items[ACTIVE] = ("mathis", json.dumps(rotated))  # Claude Code refreshed
        self.tokens["tok-a2"] = ("uuid-alice", "alice@example.com")
        self.run_ccx("use", "bob")
        self.assertEqual(self.ccx.stored("alice")["credentials"], rotated)

    def test_unsaved_active_account_is_backed_up(self):
        self.sign_in(claude_creds("tok-c"), claude_account("uuid-carol", "carol@example.com"))
        self.run_ccx("use", "bob")
        backups = [s for s in self.keychain.items if s.startswith("ai-usage-claude:_backup-")]
        self.assertEqual(len(backups), 1)

    def test_note_when_sessions_are_open(self):
        with mock.patch.object(self.ccx, "claude_sessions", lambda: 3):
            _, out = self.run_ccx("use", "bob")
        self.assertIn("NOTE: Restart open Claude Code sessions (3 running) to use this account.", out)

    def test_already_active(self):
        code, out = self.run_ccx("use", "alice")
        self.assertEqual(code, 0)
        self.assertIn("Already on", out)

    def test_refuses_to_remove_the_active_account(self):
        code, out = self.run_ccx("rm", "alice")
        self.assertEqual(code, 1)
        self.assertIn("ai-usage-claude:alice", self.keychain.items)

    def test_legacy_name_still_usable_and_removable(self):
        meta = self.read_json(".config", "ai-usage", "claude-accounts.json")
        meta["bob+old"] = meta.pop("bob")
        self.write_json(meta, ".config", "ai-usage", "claude-accounts.json")
        self.keychain.items["ai-usage-claude:bob+old"] = self.keychain.items.pop("ai-usage-claude:bob")
        self.assertEqual(self.run_ccx("use", "bob+old")[0], 0)
        self.assertEqual(self.active_creds(), self.bob_creds)
        self.run_ccx("use", "alice")
        self.assertEqual(self.run_ccx("rm", "bob+old")[0], 0)
        self.assertNotIn("ai-usage-claude:bob+old", self.keychain.items)

    def test_injection_attempt_is_rejected(self):
        code, _ = self.run_ccx("save", 'x" -s "Claude Code-credentials')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(self.keychain.items[ACTIVE][1])["claudeAiOauth"]["accessToken"], "tok-a")


class UsageTest(CcxTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in(claude_creds("tok-b"), BOB_ACCOUNT)
        self.run_ccx("save", "bob")
        self.sign_in(claude_creds("tok-a"), ALICE_ACCOUNT)
        self.run_ccx("save", "alice")

    def test_live_usage_then_throttled(self):
        rows = {r["name"]: r for r in self.ccx.account_rows()}
        self.assertEqual(rows["alice"]["windows"][0]["percent"], 12)
        self.assertTrue(rows["alice"]["active"])
        self.assertIsNone(rows["alice"]["last_seen"])
        calls = len(self.usage_calls)
        self.ccx.account_rows()  # within USAGE_TTL: no new call to the rate-limited endpoint
        self.assertEqual(len(self.usage_calls), calls)

    def test_expired_token_shows_last_known_usage(self):
        self.ccx.account_rows()
        stored = self.ccx.stored("bob")
        stored["credentials"] = claude_creds("tok-b", expires_in=-60)
        self.keychain.items["ai-usage-claude:bob"] = ("ai-usage", self.ccx.pack(stored))
        meta = self.read_json(".config", "ai-usage", "claude-accounts.json")
        meta["bob"]["usage_at"] = time.time() - 3600  # stale: would be re-read if the token allowed it
        self.write_json(meta, ".config", "ai-usage", "claude-accounts.json")
        rows = {r["name"]: r for r in self.ccx.account_rows()}
        self.assertEqual(rows["bob"]["windows"][0]["percent"], 12)
        self.assertIsNotNone(rows["bob"]["last_seen"])


if __name__ == "__main__":
    unittest.main()
