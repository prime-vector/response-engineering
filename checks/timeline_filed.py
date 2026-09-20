#!/usr/bin/env python3
"""Match a timeline to a successful receipt in its attempt's sink log."""
import hashlib
import json
import sys


def verify(output, log):
    if output.get("record_updated") is not True or not output.get("record_ref"):
        raise ValueError("Timeline must report a successful filing and record_ref.")
    payload = {key: output[key] for key in ("entries", "gaps")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    prefix = "[mock-incident_record] receipt "
    for line in log.splitlines():
        if not line.startswith(prefix):
            continue
        receipt = json.loads(line[len(prefix):])
        if (receipt.get("tool") == "record_update"
                and receipt.get("record_ref") == output["record_ref"]
                and receipt.get("payload_sha256") == digest):
            return
    raise ValueError("No successful receipt matches the timeline content and record_ref.")


if __name__ == "__main__":
    try:
        with open(sys.argv[1]) as fh:
            output = json.load(fh)
        with open(sys.argv[2]) as fh:
            verify(output, fh.read())
    except (ValueError, KeyError, OSError, IndexError) as exc:
        sys.exit(f"FAIL: {exc}")
