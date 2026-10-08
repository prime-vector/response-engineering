#!/usr/bin/env python3
# The driver files because two generations in one response can drift. One
# generated copy removes that defect until OA #105 can bind tool results into
# outputs. The mock's receipt is what checks/timeline_filed.py checks, so this
# helper and that check together are the control against reshaping the payload.
"""File a validated timeline through the sink's stateless MCP endpoint."""
import argparse
import json
import sys
import urllib.error
import urllib.request


def file_timeline(endpoint, record_ref, output):
    if not isinstance(output, dict):
        raise ValueError("Timeline must be a JSON object.")
    for key in ("entries", "gaps"):
        if not isinstance(output.get(key), list):
            raise ValueError(f"Timeline {key} must be present and a list.")
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "record_update", "arguments": {
                "record_ref": record_ref,
                "update": {"entries": output["entries"], "gaps": output["gaps"]},
            }},
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        reply = json.load(response)
    if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0" or reply.get("id") != 1:
        raise ValueError("Sink response is not the expected JSON-RPC reply.")
    if "error" in reply:
        raise ValueError("Sink returned a JSON-RPC error.")
    result = reply.get("result")
    if not isinstance(result, dict):
        raise ValueError("Sink response has no tool result.")
    if result.get("isError") is True:
        raise ValueError("Sink returned isError for record_update.")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict) or content[0].get("type") != "text":
        raise ValueError("Sink result must contain one text result.")
    try:
        accepted = json.loads(content[0]["text"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Sink text result does not parse as JSON.") from None
    if not isinstance(accepted, dict) or accepted.get("accepted") is not True:
        raise ValueError("Sink did not accept record_update.")
    if accepted.get("record_ref") != record_ref:
        raise ValueError("Sink returned a different record_ref.")
    return accepted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--record-ref", required=True)
    parser.add_argument("output_json")
    args = parser.parse_args()
    try:
        with open(args.output_json) as fh:
            output = json.load(fh)
        result = file_timeline(args.endpoint, args.record_ref, output)
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        # Response bodies and entry text stay out of failure messages.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        sys.exit(f"FAIL: {message}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
