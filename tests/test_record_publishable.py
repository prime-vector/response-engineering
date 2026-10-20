"""Offline check that a judgement record and its table are redacted alike."""
import glob
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import judgement  # noqa: E402


class WriteRecord(unittest.TestCase):
    def setUp(self):
        # A committed record, so the real markdown() renders every field it
        # reads, with the spec named absolutely: the form a caller passing
        # --spec from outside the checkout produces.
        source = sorted(glob.glob(os.path.join(
            ROOT, "evals", "results", "trial-sonnet55-medium-*.json")))[-1]
        self.result = json.load(open(source))
        self.spec = self.result["agent"]["spec"].lstrip("./")
        self.result["agent"]["spec"] = os.path.join(ROOT, self.spec)
        self.tmp = tempfile.mkdtemp()

    def test_table_is_rendered_from_the_redacted_record(self):
        path = os.path.join(self.tmp, "record.json")
        table = os.path.join(self.tmp, "record.md")
        judgement.write_record(self.result, path, table)
        for written in (open(path).read(), open(table).read()):
            self.assertNotIn(ROOT, written)
            self.assertIn(f"./{self.spec}", written)

    def test_table_is_optional(self):
        path = os.path.join(self.tmp, "record.json")
        judgement.write_record(self.result, path)
        self.assertEqual(os.listdir(self.tmp), ["record.json"])


if __name__ == "__main__":
    unittest.main()
