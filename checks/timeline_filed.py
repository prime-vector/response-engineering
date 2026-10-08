#!/usr/bin/env python3
"""Prove the driver filed exactly the contract-validated output and the sink
accepted it. True by construction, still checked because a helper that reshapes
the payload would break this control.

Usage: python3 checks/timeline_filed.py OUTPUT_JSON RECORD_REF SINK_LOG
"""
import hashlib
import json
import sys


def verify(output, record_ref, log):
    if not isinstance(output, dict):
        raise ValueError("Timeline must be a JSON object.")
    for key in ("entries", "gaps"):
        if not isinstance(output.get(key), list):
            raise ValueError(f"Timeline {key} must be present and a list.")
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
        if receipt.get("record_ref") == record_ref:
            matching_ref.append(receipt)
            if receipt.get("payload_sha256") == digest:
                return
    if not updates:
        raise ValueError("No successful record_update receipt in this attempt.")
    if not matching_ref:
        raise ValueError("No successful receipt matches record_ref " + repr(record_ref) + ".")
    accepted = [receipt.get("payload_sha256") for receipt in matching_ref]
    raise ValueError(f"Timeline payload differs from accepted update: output digest {digest}; "
                     f"accepted digests {accepted}.")


if __name__ == "__main__":
    try:
        with open(sys.argv[1]) as fh:
            output = json.load(fh)
        with open(sys.argv[3]) as fh:
            verify(output, sys.argv[2], fh.read())
    except (ValueError, KeyError, OSError, IndexError) as exc:
        sys.exit(f"FAIL: {exc}")
