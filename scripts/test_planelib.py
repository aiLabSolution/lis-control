#!/usr/bin/env python3
"""Network-free tests for scripts/planelib.py — config resolution, LIS-NN → UUID
resolution with the per-checkout cache, and state-name resolution."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planelib as pl  # noqa: E402

UUID = "12345678-1234-1234-1234-123456789abc"


class TestConfig(unittest.TestCase):
    def test_workspace_slug_env_is_bridged(self):
        env = {"PLANE_WORKSPACE": "", "PLANE_WORKSPACE_SLUG": "slugged"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(pl.workspace(), "slugged")

    def test_workspace_primary_env_wins(self):
        env = {"PLANE_WORKSPACE": "primary", "PLANE_WORKSPACE_SLUG": "slugged"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(pl.workspace(), "primary")

    def test_workspace_default(self):
        env = {"PLANE_WORKSPACE": "", "PLANE_WORKSPACE_SLUG": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(pl.workspace(), pl.WS_DEFAULT)

    def test_project_env_wins(self):
        with mock.patch.dict(os.environ, {"PLANE_PROJECT_ID": "pid-env"}, clear=False):
            self.assertEqual(pl.project(), "pid-env")


class TestResolveItem(unittest.TestCase):
    def test_uuid_goes_straight_to_single_get(self):
        with mock.patch.object(pl, "api", return_value={"id": UUID, "sequence_id": 7}) as m:
            it = pl.resolve_item(UUID)
        self.assertEqual(it["id"], UUID)
        m.assert_called_once()  # no full-backlog scan

    def test_cache_hit_uses_single_get(self):
        with tempfile.TemporaryDirectory() as td:
            cache = os.path.join(td, "c.json")
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"26": "uuid-26"}, fh)
            with mock.patch.object(pl, "CACHE", cache), \
                 mock.patch.object(pl, "api",
                                   return_value={"id": "uuid-26", "sequence_id": 26}) as m:
                it = pl.resolve_item("LIS-26")
            self.assertEqual(it["id"], "uuid-26")
            m.assert_called_once()

    def test_miss_scans_once_and_stores_everything(self):
        listing = [{"id": "u1", "sequence_id": 1}, {"id": "u2", "sequence_id": 2}]
        with tempfile.TemporaryDirectory() as td:
            cache = os.path.join(td, "c.json")
            with mock.patch.object(pl, "CACHE", cache), \
                 mock.patch.object(pl, "items", return_value=listing):
                it = pl.resolve_item("LIS-2")
            self.assertEqual(it["id"], "u2")
            with open(cache, encoding="utf-8") as fh:
                stored = json.load(fh)
            self.assertEqual(stored, {"1": "u1", "2": "u2"})  # warm for every later call

    def test_stale_cache_entry_self_heals(self):
        # cached UUID 404s (api -> None via ok404) → fall back to a fresh scan
        listing = [{"id": "live-uuid", "sequence_id": 3}]
        with tempfile.TemporaryDirectory() as td:
            cache = os.path.join(td, "c.json")
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"3": "dead-uuid"}, fh)
            with mock.patch.object(pl, "CACHE", cache), \
                 mock.patch.object(pl, "api", return_value=None), \
                 mock.patch.object(pl, "items", return_value=listing):
                it = pl.resolve_item("3")
            self.assertEqual(it["id"], "live-uuid")

    def test_unknown_key_exits(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(pl, "CACHE", os.path.join(td, "c.json")), \
                 mock.patch.object(pl, "items", return_value=[]):
                with self.assertRaises(SystemExit):
                    pl.resolve_item("LIS-999")


class TestStateId(unittest.TestCase):
    def test_uuid_passthrough_no_network(self):
        with mock.patch.object(pl, "paginate",
                               side_effect=AssertionError("must not fetch")) as _:
            self.assertEqual(pl.state_id(UUID), UUID)

    def test_name_resolves(self):
        states = [{"id": "s1", "name": "ready-for-agent"}, {"id": "s2", "name": "In Progress"}]
        with mock.patch.object(pl, "paginate", return_value=states):
            self.assertEqual(pl.state_id("ready-for-agent"), "s1")
            self.assertEqual(pl.state_id("in progress"), "s2")  # case-insensitive fallback

    def test_unknown_name_exits_with_choices(self):
        with mock.patch.object(pl, "paginate", return_value=[{"id": "s1", "name": "Done"}]):
            with self.assertRaises(SystemExit):
                pl.state_id("no-such-state")


class TestStateName(unittest.TestCase):
    def test_expanded_dict(self):
        self.assertEqual(pl.state_name({"state": {"name": "Backlog"}}), "Backlog")

    def test_bare_uuid_string(self):
        self.assertEqual(pl.state_name({"state": "some-uuid"}), "some-uuid")

    def test_missing(self):
        self.assertEqual(pl.state_name({}), "?")


if __name__ == "__main__":
    unittest.main()
