#!/usr/bin/env python3
"""Network-free tests for scripts/slice.py helpers."""
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


if __name__ == "__main__":
    unittest.main()
