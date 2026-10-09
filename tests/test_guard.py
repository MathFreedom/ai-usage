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
