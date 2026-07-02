#!/usr/bin/env python3
"""Network-free tests for scripts/slice.py helpers — agent identity and the
claim-ledger reduce (parse, TTL, release, quote handling)."""
import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
slice_mod = importlib.import_module("slice")


class TestAgentIdentity(unittest.TestCase):
    def test_explicit_agent_wins(self):
        with mock.patch.dict(os.environ, {"LIS_AGENT_ID": "lis-agent"}, clear=False):
            self.assertEqual(slice_mod._agent_id("explicit"), "explicit")

    def test_lis_agent_id_wins_over_tool_session(self):
        env = {"LIS_AGENT_ID": "lis-agent", "CODEX_THREAD_ID": "codex-thread"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(slice_mod._agent_id(), "lis-agent")

    def test_codex_thread_id_is_used_for_codex_sessions(self):
        env = {
            "LIS_AGENT_ID": "",
            "CODEX_THREAD_ID": "codex-thread",
            "CODEX_SESSION_ID": "codex-session",
            "CLAUDE_CODE_SESSION_ID": "claude-session",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(slice_mod._agent_id(), "codex-thread")

    def test_codex_session_id_is_secondary_codex_fallback(self):
        env = {
            "LIS_AGENT_ID": "",
            "CODEX_THREAD_ID": "",
            "CODEX_SESSION_ID": "codex-session",
            "CLAUDE_CODE_SESSION_ID": "claude-session",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(slice_mod._agent_id(), "codex-session")

    def test_claude_session_id_still_works(self):
        env = {
            "LIS_AGENT_ID": "",
            "CODEX_THREAD_ID": "",
            "CODEX_SESSION_ID": "",
            "CLAUDE_CODE_SESSION_ID": "claude-session",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(slice_mod._agent_id(), "claude-session")


class TestLedger(unittest.TestCase):
    """_read_claims reduces raw comment rows to live per-agent ownership."""

    def _claims(self, rows):
        with mock.patch.object(slice_mod.pl, "paginate", return_value=rows):
            return slice_mod._read_claims("issue-uuid")

    def test_claim_then_release_frees_the_slice(self):
        rows = [
            {"created_at": "2026-07-02T10:00:00+00:00",
             "comment_stripped": "LIS-CLAIM v1 agent=a task='x' until=2099-01-01T00:00:00+00:00"},
            {"created_at": "2026-07-02T10:05:00+00:00",
             "comment_stripped": "LIS-RELEASE v1 agent=a"},
        ]
        self.assertEqual(self._claims(rows), {})

    def test_live_claim_parses_fields(self):
        rows = [{"created_at": "2026-07-02T10:00:00+00:00",
                 "comment_stripped":
                     "LIS-CLAIM v1 agent=sess-1 task='ASTM thread' until=2099-01-01T00:00:00+00:00"}]
        c = self._claims(rows)["sess-1"]
        self.assertTrue(c["active"])
        self.assertEqual(c["task"], "ASTM thread")
        self.assertEqual(c["verb"], "CLAIM")

    def test_expired_ttl_is_inactive_not_dropped(self):
        rows = [{"created_at": "2020-01-01T00:00:00+00:00",
                 "comment_stripped": "LIS-CLAIM v1 agent=a until=2020-01-02T00:00:00+00:00"}]
        c = self._claims(rows)["a"]
        self.assertFalse(c["active"])

    def test_naive_until_does_not_crash(self):
        # a hand-written stamp without an offset used to raise TypeError (naive vs aware)
        rows = [{"created_at": "2026-07-02T10:00:00+00:00",
                 "comment_stripped": "LIS-CLAIM v1 agent=a until=2099-01-01T00:00:00"}]
        c = self._claims(rows)["a"]
        self.assertTrue(c["active"])  # naive treated as UTC; 2099 is live

    def test_garbage_until_stays_active(self):
        rows = [{"created_at": "t", "comment_stripped": "LIS-CLAIM v1 agent=a until=not-a-date"}]
        self.assertTrue(self._claims(rows)["a"]["active"])

    def test_old_repr_double_quoted_task_still_parses(self):
        # pre-rework ledger lines used task={task!r}; keep reading them
        rows = [{"created_at": "t",
                 "comment_stripped": 'LIS-CLAIM v1 agent=a task="legacy task" until=2099-01-01T00:00:00+00:00'}]
        self.assertEqual(self._claims(rows)["a"]["task"], "legacy task")

    def test_post_ledger_curly_quotes_task(self):
        # a task mixing both ASCII quote kinds must still round-trip through the regex
        sent = {}

        def fake_api(method, path, params=None, body=None, **kw):
            sent.update(body or {})

        with mock.patch.object(slice_mod.pl, "api", side_effect=fake_api), \
             mock.patch.object(slice_mod.pl, "project", return_value="proj"):
            slice_mod._post_ledger("iid", "CLAIM", "a", "it's a \"quoted\" task")
        m = slice_mod._LEDGER_RE.search(sent["comment_html"])
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "it’s a ”quoted” task")

    def test_heartbeat_updates_until(self):
        rows = [
            {"created_at": "2026-07-02T10:00:00+00:00",
             "comment_stripped": "LIS-CLAIM v1 agent=a task='x' until=2020-01-01T00:00:00+00:00"},
            {"created_at": "2026-07-02T11:00:00+00:00",
             "comment_stripped": "LIS-HEARTBEAT v1 agent=a task='x' until=2099-01-01T00:00:00+00:00"},
        ]
        c = self._claims(rows)["a"]
        self.assertTrue(c["active"])
        self.assertEqual(c["verb"], "HEARTBEAT")


if __name__ == "__main__":
    unittest.main()
