"""Act three's wiring, driven with a stub `oa` and the real mock sink.

The acceptance run proves one execution. This proves the sequence the driver
is relied on for: the Scribe stage retries on the transport (so it is oa_run,
not oa_run_once), the driver files the surviving reply and nothing else, the
receipt check runs inside the surviving attempt's log window, and an earlier
attempt's receipt is outside it. Costs nothing and needs no key.

One step is held structurally rather than behaviourally: that the receipt
check is invoked at all. A driver that files correctly cannot make that check
fail, so its removal is invisible to a passing run and is caught by reading
the act instead.
"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SINK_PORT = 8425

TIMELINE = {
    "entries": [{"at": "2026-03-02T03:17:00+00:00", "event": "synthetic detection",
                 "source": "signals[0].problems[0]", "consumed_by_human": False,
                 "confidence": "confirmed", "falsifying_test": "the problem feed showing otherwise"}],
    "gaps": [{"description": "a log never produced", "how_to_obtain": "request it",
              "still_outstanding": True}],
}
BOGUS = {"entries": [{"event": "an earlier attempt's copy"}], "gaps": []}

# Attempt one files a bogus payload on the sink, as a tool-calling task would
# have, then dies on the transport. Attempt two returns the timeline. A driver
# that does not retry fails here; one that reads the whole log sees two
# receipts; one that files the wrong thing, or nothing, fails its own check.
STUB = """#!/usr/bin/env bash
attempt=$(( $(cat "$STUB_WORK/attempts" 2>/dev/null || echo 0) + 1 ))
echo "$attempt" > "$STUB_WORK/attempts"
printf '%s\\0' "$@" >> "$STUB_WORK/arguments-$attempt"
if [ "$attempt" -eq 1 ]; then
  python3 demos/file_timeline.py --endpoint http://localhost:8425 --record-ref SYN-0001 "$STUB_WORK/bogus.json" >/dev/null
  echo '{"code": "PROVIDER_ERROR", "error": "Anthropic request failed: Remote end closed connection without response"}' >&2
  exit 1
fi
cat "$STUB_WORK/timeline.json"
"""


def port_free(port, wait=5.0):
    # A failed act leaves the adapter to the driver's exit trap, and the kill
    # lands a moment after the driver returns; allow that moment before
    # deciding the port belongs to someone else.
    deadline = time.monotonic() + wait
    while True:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)


class ActThree(unittest.TestCase):
    def setUp(self):
        self.assertTrue(port_free(SINK_PORT), f"port {SINK_PORT} is in use; the driver must own the sink")
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        (self.work / "bin").mkdir()
        (self.work / "bin" / "oa").write_text(STUB)
        (self.work / "bin" / "oa").chmod(0o755)
        (self.work / "timeline.json").write_text(json.dumps(TIMELINE))
        (self.work / "bogus.json").write_text(json.dumps(BOGUS))
        env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
        env.update(PATH=f"{self.work / 'bin'}:{env.get('PATH', '')}", ANTHROPIC_API_KEY="stub",
                   STUB_WORK=str(self.work), TMPDIR=str(self.work))
        self.env = env

    def run_act3(self):
        result = subprocess.run(["bash", "demos/investigate.sh", "act3"], cwd=ROOT, env=self.env,
                                capture_output=True, text=True, timeout=120)
        match = re.search(r"Pipeline outputs and adapter logs: (\S+)", result.stdout)
        out = Path(match.group(1)) if match else None
        return result, out

    def test_retries_files_the_surviving_reply_and_checks_within_its_window(self):
        result, out = self.run_act3()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.work / "attempts").read_text().strip(), "2", "the stage did not retry: not oa_run")
        self.assertIn("retrying once", result.stderr)
        self.assertIn("filed as SYN-0001 (receipt verified against the adapter log)", result.stdout)
        self.assertEqual(json.loads((out / "act3-timeline.json").read_text()), TIMELINE)
        self.assertTrue((out / "act3-filing.json").exists(), "the driver did not file")
        self.assertEqual(json.loads((out / "act3-filing.json").read_text())["record_ref"], "SYN-0001")
        full = (out / "adapter-incident_record.log").read_text()
        window = (out / "act3-sink.log").read_text()
        self.assertEqual(full.count("] receipt "), 2, "both attempts' filings should be on the sink log")
        self.assertEqual(window.count("] receipt "), 1, "the window should hold only the surviving attempt")
        self.assertNotIn(json.loads(full.splitlines()[[i for i, l in enumerate(full.splitlines()) if "] receipt " in l][0]].split("] receipt ", 1)[1])["payload_sha256"], window)
        # The receipt the check saw is the driver's filing of exactly this reply.
        subprocess.run(["python3", "checks/timeline_filed.py", str(out / "act3-timeline.json"), "SYN-0001",
                        str(out / "act3-sink.log")], cwd=ROOT, check=True)

    def test_a_reply_the_driver_cannot_file_fails_the_act(self):
        # Without entries the helper refuses before any request, and the act
        # fails closed rather than reporting a filing that never happened.
        (self.work / "timeline.json").write_text(json.dumps({"entries": "none", "gaps": []}))
        result, out = self.run_act3()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL: Timeline entries must be present and a list", result.stderr)
        self.assertEqual(result.stdout.count("receipt verified"), 0)


class ActThreeSteps(unittest.TestCase):
    def test_the_act_runs_its_four_steps_in_order(self):
        driver = (ROOT / "demos" / "investigate.sh").read_text()
        act = driver[driver.index("act3() {"):]
        act = act[:act.index("\n}\n")]
        steps = [
            'oa_run --spec .agents/scribe.yaml --task timeline',
            'python3 demos/file_timeline.py --endpoint http://localhost:8425 --record-ref "$ref"',
            'attempt_log "$OUT/adapter-incident_record.log" > "$OUT/act3-sink.log"',
            'python3 checks/timeline_filed.py "$OUT/act3-timeline.json" "$ref" "$OUT/act3-sink.log"',
        ]
        positions = [act.find(step) for step in steps]
        for step, position in zip(steps, positions):
            self.assertNotEqual(position, -1, f"act three no longer runs: {step}")
        self.assertEqual(positions, sorted(positions), "act three's steps are out of order")
        self.assertNotIn("oa_run_once", act, "the timeline stage must retry: it has one effect, its output")
