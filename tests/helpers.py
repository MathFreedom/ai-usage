"""Shared test helpers: load bin/cx and bin/ccx in a throwaway HOME, behind a guard that fails
any test reaching a real process, network or socket, with an in-memory fake of macOS `security`.
"""
import _posixsubprocess  # noqa: F401  (patched by the guard)
import _socket  # noqa: F401
import base64
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REAL_POPEN = subprocess.Popen  # captured before any guard is installed
_REAL_FORK_EXEC = _posixsubprocess.fork_exec  # what Popen itself uses to start the child


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def real_run(args, input=None, env=None, timeout=20):
    """Run a repo script for real (status line tests only), bypassing the guard. It runs in its
    own session: `pid` is the process group of everything it starts, and the whole group is
    killed if it overruns the timeout, so a hanging script can't hang the suite."""
    with mock.patch("_posixsubprocess.fork_exec", _REAL_FORK_EXEC), \
            _REAL_POPEN(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, env=env, start_new_session=True) as proc:
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            proc.communicate()
            raise
    result = subprocess.CompletedProcess(args, proc.returncode, out, err)
    result.pid = proc.pid
    return result


def wait_group_gone(pgid, deadline_s=10):
    """Wait until no process of the group is left (background jobs included)."""
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


class RealCallBlocked(AssertionError):
    pass


def _blocked(what):
    def fail(*args, **kwargs):
        raise RealCallBlocked(f"test reached a real {what}: {args[:1]}")
    fail.ai_usage_guard = True  # lets test_guard check what is guarded without calling it
    return fail


def load_tool(name):
    """Load bin/<name> (no .py extension) as a fresh module; paths come from the current HOME."""
    path = os.path.join(ROOT, "bin", name)
    module_name = f"{name}_under_test_{time.monotonic_ns()}"
    loader = importlib.machinery.SourceFileLoader(module_name, path)
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeSecurity:
    """In-memory stand-in for /usr/bin/security, as ccx calls it through subprocess.run."""

    MAX_LINE = 4096  # `security -i` mangles longer lines

    def __init__(self):
        self.items = {}  # service -> (account, secret)
        self.commands = []  # argv of every call, to check no secret reaches argv
        self.fail_writes = False  # simulate a locked Keychain / denied write

    def run(self, args, input=None, capture_output=False, text=False, **kwargs):
        self.commands.append(list(args))
        verb = args[1] if len(args) > 1 else ""
        out, code = "", 0
        if verb == "find-generic-password":
            service = args[args.index("-s") + 1]
            if service in self.items:
                out = self.items[service][1] + "\n"
            else:
                code = 44
        elif verb == "-i" and self.fail_writes:
            return subprocess.CompletedProcess(args, 1, "", "security: SecKeychainItemCreate: error")
        elif verb == "-i":
            # Parsed like the real tool would: shell-style words, the last -a/-s/-X wins. A name
            # that smuggles quotes or options in therefore really reaches another item here.
            for line in (input or "").splitlines():
                if len(line) > self.MAX_LINE:
                    return subprocess.CompletedProcess(args, 0, "", "security: unknown command")
                words = shlex.split(line)
                if not words or words[0] != "add-generic-password":
                    return subprocess.CompletedProcess(args, 1, "", f"error: {line[:40]}")
                opts = {}
                i = 1
                while i < len(words):
                    if words[i] in ("-a", "-s", "-X") and i + 1 < len(words):
                        opts[words[i]] = words[i + 1]
                        i += 2
                    else:
                        i += 1
                self.items[opts["-s"]] = (opts.get("-a", ""), bytes.fromhex(opts["-X"]).decode())
        elif verb == "delete-generic-password":
            self.items.pop(args[args.index("-s") + 1], None)
        elif verb == "dump-keychain":
            out = "".join(f'    "svce"<blob>="{s}"\n' for s in self.items)
        else:
            raise RealCallBlocked(f"unexpected security call {args}")
        return subprocess.CompletedProcess(args, code, out, "")


class SafeTestCase(unittest.TestCase):
    """Temp HOME + guard: subprocess.run, urlopen and sockets fail unless a test fakes them."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="ai-usage-test-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        env = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "CLAUDE_CONFIG_DIR")}
        env["HOME"] = self.home
        for patcher in (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch("subprocess.run", _blocked("process")),
            mock.patch("subprocess.Popen", _blocked("process")),  # also covers call/check_output
            mock.patch("os.system", _blocked("process")),
            mock.patch("os.posix_spawn", _blocked("process")),
            mock.patch("urllib.request.urlopen", _blocked("network call")),
            mock.patch("socket.socket", _blocked("socket")),
            mock.patch("socket.getaddrinfo", _blocked("DNS lookup")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # Every other way to start a process, resolve a name or open a socket.
        targets = [f"os.{n}" for n in ("posix_spawnp", "fork", "forkpty", "spawnv", "spawnve",
                                        "spawnvp", "spawnvpe", "execv", "execve", "execvp",
                                        "execvpe", "popen") if hasattr(os, n)]
        targets += ["_posixsubprocess.fork_exec", "_socket.socket"]
        targets += [f"socket.{n}" for n in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                                             "getnameinfo", "create_connection")]
        for target in targets:
            patcher = mock.patch(target, _blocked("process" if "socket" not in target else "network"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def write_json(self, data, *parts):
        path = self.path(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def read_json(self, *parts):
        with open(self.path(*parts)) as f:
            return json.load(f)


# Fake credentials

def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def codex_auth(email, user_id, account_id, plan="pro", refresh="r1"):
    """A Codex ~/.codex/auth.json for a ChatGPT account (JWTs are unsigned: only claims matter)."""
    claims = {"email": email, "https://api.openai.com/auth": {
        "chatgpt_user_id": user_id, "chatgpt_plan_type": plan, "chatgpt_account_id": account_id}}
    access = {"exp": int(time.time()) + 86400}
    return {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {
        "id_token": f"h.{_b64(claims)}.s", "access_token": f"h.{_b64(access)}.s",
        "refresh_token": refresh, "account_id": account_id}}


def claude_creds(token, expires_in=3600, refresh="r1", plan="max"):
    """The JSON Claude Code keeps in the Keychain item "Claude Code-credentials"."""
    return {"claudeAiOauth": {
        "accessToken": token, "refreshToken": refresh,
        "expiresAt": int((time.time() + expires_in) * 1000),
        "scopes": ["user:inference", "user:profile"], "subscriptionType": plan,
        "rateLimitTier": "default_claude_max_20x"}}


def claude_account(uuid, email):
    """The oauthAccount block of ~/.claude.json."""
    return {"accountUuid": uuid, "emailAddress": email, "organizationUuid": f"org-{uuid}",
            "displayName": email.split("@")[0], "billingType": "stripe_subscription"}
