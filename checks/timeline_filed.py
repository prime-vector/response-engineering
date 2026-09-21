#!/usr/bin/env python3
"""Match a timeline to a successful receipt in its attempt's sink log."""
import hashlib
import json
import sys


def verify(output, log):
    if not isinstance(output, dict):
        raise ValueError("Timeline must be a JSON object.")
    if output.get("record_updated") is not True or not output.get("record_ref"):
        raise ValueError("Timeline must report a successful filing and record_ref.")
    payload = {key: output[key] for key in ("entries", "gaps")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    prefix = "[mock-incident_record] receipt "
    updates = []
    matching_ref = []
    for line in log.splitlines():
        if not line.startswith(prefix):
            continue
        receipt = json.loads(line[len(prefix):])
        if not isinstance(receipt, dict):
            raise ValueError("Sink receipt must be a JSON object.")
        if receipt.get("tool") != "record_update":
            continue
        updates.append(receipt)
        if receipt.get("record_ref") == output["record_ref"]:
            matching_ref.append(receipt)
            if receipt.get("payload_sha256") == digest:
                return
    if not updates:
        raise ValueError("No successful record_update receipt in this attempt.")
    if not matching_ref:
        raise ValueError("No successful receipt matches record_ref " + repr(output["record_ref"]) + ".")
    accepted = [receipt.get("payload_sha256") for receipt in matching_ref]
    raise ValueError(f"Timeline payload differs from accepted update: output digest {digest}; "
                     f"accepted digests {accepted}.")


if __name__ == "__main__":
    try:
        with open(sys.argv[1]) as fh:
            output = json.load(fh)
        with open(sys.argv[2]) as fh:
            verify(output, fh.read())
    except (ValueError, KeyError, OSError, IndexError) as exc:
        sys.exit(f"FAIL: {exc}")
