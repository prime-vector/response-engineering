"""Offline check that a judgement record and its table are redacted alike."""
import glob
import json
import os
import sys
import tempfile
import unittest

import yaml

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
        with open(source) as handle:
            self.result = json.load(handle)
        self.spec = self.result["agent"]["spec"].lstrip("./")
        self.result["agent"]["spec"] = os.path.join(ROOT, self.spec)
        self.tmp = tempfile.mkdtemp()

    def test_table_is_rendered_from_the_redacted_record(self):
        path = os.path.join(self.tmp, "record.json")
        table = os.path.join(self.tmp, "record.md")
        judgement.write_record(self.result, path, table)
        for name in (path, table):
            with open(name) as handle:
                written = handle.read()
            self.assertNotIn(ROOT, written)
            self.assertIn(f"./{self.spec}", written)

    def test_table_is_optional(self):
        path = os.path.join(self.tmp, "record.json")
        judgement.write_record(self.result, path)
        self.assertEqual(os.listdir(self.tmp), ["record.json"])


# Every path load_config holds, as (description, getter, setter) on the
# parsed config, so each field is driven on its own.
FIELDS = [
    ("spec", lambda c: c["spec"],
     lambda c, v: c.__setitem__("spec", v)),
    ("arm judgement-heading index", lambda c: c["arms"][0]["index"],
     lambda c, v: c["arms"][0].__setitem__("index", v)),
    ("arm judgement-single-query system_prompt",
     lambda c: c["arms"][2]["system_prompt"],
     lambda c, v: c["arms"][2].__setitem__("system_prompt", v)),
    ("judge groundedness_prompt", lambda c: c["judge"]["groundedness_prompt"],
     lambda c, v: c["judge"].__setitem__("groundedness_prompt", v)),
    ("judge divergence_prompt", lambda c: c["judge"]["divergence_prompt"],
     lambda c, v: c["judge"].__setitem__("divergence_prompt", v)),
]
CONFIG = os.path.join(ROOT, "evals", "config.judgement.yaml")


class LoadConfig(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, self.cwd)
        self.tmp = tempfile.mkdtemp()

    def load(self, raw):
        path = os.path.join(self.tmp, "config.yaml")
        with open(path, "w") as handle:
            yaml.safe_dump(raw, handle)
        return judgement.load_config(path)

    def test_an_absolute_path_inside_the_checkout_is_named_relative(self):
        shipped = judgement.load_config(CONFIG)
        for name, get, put in FIELDS:
            with self.subTest(name):
                raw = yaml.safe_load(open(CONFIG))
                put(raw, os.path.join(ROOT, get(raw)))
                self.assertEqual(get(self.load(raw)), get(shipped))

    def test_a_path_outside_the_checkout_is_refused(self):
        outside = os.path.join(self.tmp, "variant.yaml")
        for name, get, put in FIELDS:
            with self.subTest(name):
                raw = yaml.safe_load(open(CONFIG))
                put(raw, outside)
                with self.assertRaises(SystemExit) as raised:
                    self.load(raw)
                self.assertIn(f"{name} is outside this checkout",
                              str(raised.exception))

    def test_drift_reads_an_absolute_config_as_the_recorded_files(self):
        # The gate's reproduction: the same files named absolutely in the
        # config must not read as a different spec, prompt or index.
        record = json.load(open(sorted(glob.glob(os.path.join(
            ROOT, "evals", "results",
            "judgement-single-query-*.json")))[-1]))
        absolute = yaml.safe_load(open(CONFIG))
        for name, get, put in FIELDS:
            put(absolute, os.path.join(ROOT, get(absolute)))
        for arm in absolute["arms"]:
            arm["index"] = os.path.join(ROOT, arm["index"])
        shipped = judgement.load_config(CONFIG)
        loaded = self.load(absolute)
        arm = judgement.pick_arm(shipped, "judgement-single-query")
        self.assertEqual(
            judgement.record_drift(loaded, judgement.pick_arm(
                loaded, "judgement-single-query"), record),
            judgement.record_drift(shipped, arm, record))


if __name__ == "__main__":
    unittest.main()
