"""The guard itself: a test that forgets to fake something must fail, not reach the real system."""
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

    def test_os_level_process_apis_are_blocked(self):
        import os
        calls = [lambda: os.fork(), lambda: os.forkpty(), lambda: os.popen("true"),
                 lambda: os.posix_spawnp("true", ["true"], dict(os.environ)),
                 lambda: os.execv("/usr/bin/true", ["true"]),
                 lambda: os.spawnv(os.P_WAIT, "/usr/bin/true", ["true"])]
        for call in calls:
            with self.assertRaises(RealCallBlocked):
                call()

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
