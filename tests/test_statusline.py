"""claude/statusline.sh — run for real (jq required) with a temp HOME and payloads on stdin."""
import json
import os
import re
import time
import unittest

from helpers import ROOT, SafeTestCase, kill_group, real_run, wait_group_gone

SCRIPT = os.path.join(ROOT, "claude", "statusline.sh")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class StatusLineTest(SafeTestCase):
    def run_raw(self, payload, keep_background=False):
        env = {"HOME": self.home, "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
        r = real_run(["/bin/sh", SCRIPT], input=json.dumps(payload), env=env)
        if not keep_background:
            kill_group(r.pid)  # nothing the script left in the background survives the test
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def run_line(self, payload):
        return ANSI.sub("", self.run_raw(payload).stdout)

    def cache(self):
        return self.read_json(".claude", "usage-cache.json")["rate_limits"]

    def payload(self, five=None, week=None, cache_left=2820):
        now = int(time.time())
        limits = {}
        if five:
            limits["five_hour"] = {"used_percentage": five[0], "resets_at": now + five[1]}
        if week:
            limits["seven_day"] = {"used_percentage": week[0], "resets_at": now + week[1]}
        return {"model": {"display_name": "Opus 5.5"},
                "prompt_cache": {"warm": True, "expires_at": now + cache_left},
                "rate_limits": limits}

    def setUp(self):
        super().setUp()
        os.makedirs(self.path(".claude"))

    def test_line_format(self):
        line = self.run_line(self.payload(five=(5, 12630), week=(2, 5 * 86400 + 600)))  # margins: seconds may pass
        self.assertEqual(line, "Opus 5.5 │ cache 47m │ session: 3h30 5% │ weekly: 5d 2%")

    def test_zero_padded_minutes_and_cache_rounding(self):
        line = self.run_line(self.payload(five=(5, 3 * 3600 + 5 * 60 + 30), cache_left=2770))
        self.assertIn("session: 3h05 5%", line)
        self.assertIn("cache 47m", line)  # 46.2 minutes left: rounded up, not to nearest

    def test_colors_follow_the_percentage(self):
        red, yellow, green = "\x1b[31m", "\x1b[33m", "\x1b[32m"
        for pct, color in ((85, red), (80, red), (79, yellow), (50, yellow), (49, green), (10, green)):
            out = self.run_raw(self.payload(five=(pct, 12630))).stdout
            self.assertIn(f"{color}3h30 {pct}%", out, pct)

    def test_expired_cache(self):
        line = self.run_line(self.payload(five=(5, 12600), cache_left=-10))
        self.assertIn("cache expired", line)

    def test_stale_snapshot_never_drops_a_window(self):
        fresh = self.payload(five=(4, 9000), week=(2, 500000))
        self.run_line(fresh)
        stale = {"rate_limits": {"seven_day": {"used_percentage": 1,
                                               "resets_at": fresh["rate_limits"]["seven_day"]["resets_at"]}}}
        self.run_line(stale)
        self.assertEqual(self.cache()["five_hour"]["used_percentage"], 4)
        self.assertEqual(self.cache()["seven_day"]["used_percentage"], 2)  # same window: higher % wins

    def test_later_window_wins(self):
        self.run_line(self.payload(five=(40, 600)))
        self.run_line(self.payload(five=(1, 18600)))  # new 5-hour window
        self.assertEqual(self.cache()["five_hour"]["used_percentage"], 1)

    def test_older_window_never_replaces_a_newer_one(self):
        self.run_line(self.payload(five=(1, 18600)))
        self.run_line(self.payload(five=(40, 600)))  # late snapshot from an idle session
        self.assertEqual(self.cache()["five_hour"]["used_percentage"], 1)

    def test_chain_into_itself_runs_once(self):
        # A previous status line pointing at this very script must not loop forever.
        counter = self.path("chained")
        chain = f'/bin/sh "{SCRIPT}" >/dev/null; echo run >> "{counter}"'
        os.makedirs(self.path(".config", "ai-usage"))
        with open(self.path(".config", "ai-usage", "statusline-chain"), "w") as f:
            f.write(chain + "\n")
        r = self.run_raw(self.payload(five=(5, 12600)), keep_background=True)
        # Wait for every process the run started, background chain included: a chain looping
        # into itself never finishes, so this fails instead of passing on timing luck.
        gone = wait_group_gone(r.pid)
        if not gone:
            kill_group(r.pid)  # never leave a runaway chain behind
        self.assertTrue(gone, "chained status line still running")
        with open(counter) as f:
            self.assertEqual(f.read().count("run"), 1)


if __name__ == "__main__":
    unittest.main()
