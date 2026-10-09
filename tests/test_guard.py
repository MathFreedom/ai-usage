"""The guard itself: a test that forgets to fake something must fail, not reach the real system.

Process APIs are checked by identity, never called: an unguarded os.execv or os.fork would replace
or duplicate the test process itself, and a silent exit could look like a passing suite."""
import importlib
import socket
import subprocess
import unittest
import urllib.request

from helpers import RealCallBlocked, SafeTestCase


class GuardTest(SafeTestCase):
    def test_real_process_is_blocked(self):
        with self.assertRaises(RealCallBlocked):
            subprocess.run(["/usr/bin/security", "dump-keychain"])

    def test_other_process_apis_are_blocked(self):
        import os
        for call in (lambda: subprocess.Popen(["/usr/bin/true"]), lambda: subprocess.check_output(["/usr/bin/true"]),
                     lambda: os.system("true")):
            with self.assertRaises(RealCallBlocked):
                call()

    # Written here, independently of helpers.py: dropping an entry there must fail this test.
    REQUIRED = [
        ("subprocess", "run"), ("subprocess", "Popen"), ("_posixsubprocess", "fork_exec"),
        ("os", "system"), ("os", "popen"), ("os", "fork"), ("os", "forkpty"),
        ("os", "posix_spawn"), ("os", "posix_spawnp"),
        ("os", "execv"), ("os", "execve"), ("os", "execvp"), ("os", "execvpe"),
        ("os", "spawnv"), ("os", "spawnve"), ("os", "spawnvp"), ("os", "spawnvpe"),
        ("socket", "socket"), ("_socket", "socket"), ("socket", "getaddrinfo"),
        ("socket", "gethostbyname"), ("socket", "gethostbyname_ex"), ("socket", "gethostbyaddr"),
        ("socket", "getnameinfo"), ("socket", "create_connection"),
        ("urllib.request", "urlopen"),
    ]

    def test_every_process_and_network_entry_point_is_guarded(self):
        for module, name in self.REQUIRED:
            obj = getattr(importlib.import_module(module), name)
            self.assertTrue(getattr(obj, "ai_usage_guard", False), f"{module}.{name} is not guarded")

    def test_dns_is_blocked(self):
        for call in (lambda: socket.getaddrinfo("api.anthropic.com", 443),
                     lambda: socket.gethostbyname("api.anthropic.com"),
                     lambda: socket.create_connection(("api.anthropic.com", 443))):
            with self.assertRaises(RealCallBlocked):
                call()

    def test_real_network_is_blocked(self):
        with self.assertRaises(RealCallBlocked):
            urllib.request.urlopen("https://api.anthropic.com/api/oauth/usage")

    def test_real_socket_is_blocked(self):
        with self.assertRaises(RealCallBlocked):
            socket.socket(socket.AF_UNIX)

    def test_home_is_a_temp_dir(self):
        import os
        self.assertTrue(os.environ["HOME"].startswith(self.home))
        self.assertNotIn("CODEX_HOME", os.environ)


if __name__ == "__main__":
    unittest.main()
