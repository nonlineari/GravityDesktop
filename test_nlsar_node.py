#!/usr/bin/env python3
"""NLSAR connection node: merge local architecture snapshot into gravity_update."""

import unittest
from pathlib import Path
from unittest.mock import patch

import nlsar_node


class NlsarNodeTests(unittest.TestCase):
    def test_merge_into_jobs(self):
        snap = {"type": "gravity_update", "jobs": [{"id": 1, "title": "yt"}], "catalog": []}
        nls = {
            "jobs": [{"id": 42120, "title": "nlsar-recrawl", "status": "idle"}],
            "catalog": [{"title": "bandcamp-nls", "n": 2}],
            "corpus": 314,
            "signals": ["HANDSHAKE"],
            "listen": "http://127.0.0.1:4212/",
        }
        out = nlsar_node.merge_into(snap, nls)
        self.assertTrue(out["nlsar"]["connected"])
        titles = [j["title"] for j in out["jobs"]]
        self.assertIn("yt", titles)
        self.assertIn("nlsar-recrawl", titles)
        self.assertEqual(out["catalog"][0]["title"], "bandcamp-nls")

    def test_merge_offline(self):
        out = nlsar_node.merge_into({"jobs": [], "catalog": []}, None)
        self.assertFalse(out["nlsar"]["connected"])

    def test_attach_nav(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            nav = Path(tmp) / "remote-nav.tsv"
            with patch.object(nlsar_node, "NAV", nav):
                path = nlsar_node.attach_nav("http://127.0.0.1:4212")
            text = Path(path).read_text(encoding="utf-8")
        self.assertIn("nlsar\thttp://127.0.0.1:4212\t1\tbot", text)
        self.assertIn("nlsar-station", text)


if __name__ == "__main__":
    unittest.main()
