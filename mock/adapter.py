#!/usr/bin/env python3
"""
Mock MCP adapter for the telemetry and change_registry surfaces.

Serves interfaces/TELEMETRY.md over JSON-RPC 2.0 on plain HTTP, backed
entirely by a generated fixture view. Stdlib only, no dependencies.

This is not a throwaway: it is the conformance reference. A vendor adapter
is correct when it satisfies the same tool surface against the same fixtures.

The adapter serves whatever fixture view it is started with, and nothing
else. Time-honesty comes from the view (a D+1 view simply contains no
process snapshot and no change query), and tool access comes from each
spec's sandbox. The adapter enforces neither; it just refuses to invent
data the view does not hold.

    python3 mock/adapter.py --surface telemetry                            # 8422
    python3 mock/adapter.py --surface change_registry                      # 8423
    python3 mock/adapter.py --surface host                                 # 8424
    python3 mock/adapter.py --surface telemetry --fixture fixtures/composite-incident.d1.json

MCP tool names use underscores (problems_list) rather than the dotted
interface names (problems.list): model-facing tool name constraints do not
allow dots.
"""

import argparse
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORTS = {"telemetry": 8422, "change_registry": 8423, "host": 8424}
DEFAULT_FIXTURE = "fixtures/composite-incident.json"

FIXTURE = {}
SURFACE = ""


def _ts(value):
    return datetime.fromisoformat(value)


def _signal(sig_type):
    for sig in FIXTURE.get("signals", []):
        if sig.get("type") == sig_type:
            return sig
    return None


def _check_entity(entity_id):
    known = FIXTURE["entity"]["entity_id"]
    if entity_id != known:
        raise ToolFault(f"Unknown entity '{entity_id}'. This fixture holds '{known}'.")


class ToolFault(Exception):
    """A tool-level failure the model should see as a result, not a crash."""


# --- telemetry surface -------------------------------------------------------

def problems_list(args):
    _check_entity(args["entity_id"])
    feed = _signal("problem_feed")
    lo = _ts(args["from"]) if args.get("from") else None
    hi = _ts(args["to"]) if args.get("to") else None
    include_closed = args.get("include_closed", True)

    problems = []
    for p in feed["problems"]:
        opened = _ts(p["opened_at"])
        if lo and opened < lo:
            continue
        if hi and opened > hi:
            continue
        if not include_closed and p["closed_at"] is not None:
            continue
        problems.append(p)

    return {
        "problems": problems,
        "total": len(problems),
        "unacknowledged": sum(1 for p in problems if p["acknowledged_by"] is None),
        "window_queried": {"from": args.get("from") or feed["window"]["from"],
                           "to": args.get("to") or feed["window"]["to"]},
        "note": feed.get("note"),
    }


def metrics_query(args):
    _check_entity(args["entity_id"])
    metric = args["metric"]
    series_sig = _signal("metric_series")

    if metric == series_sig["metric"]:
        lo = _ts(args["from"]) if args.get("from") else None
        hi = _ts(args["to"]) if args.get("to") else None
        series = [pt for pt in series_sig["series"]
                  if (lo is None or _ts(pt["t"]) >= lo)
                  and (hi is None or _ts(pt["t"]) <= hi)]
        return {"metric": metric, "unit": series_sig["unit"],
                "resolution": series_sig["resolution"], "series": series}

    if metric == "memory.total":
        total = FIXTURE["entity"]["capacity"]["memory_bytes"]
        return {"metric": metric, "unit": "bytes", "resolution": "static",
                "series": [{"t": FIXTURE["as_of"], "v": total}],
                "note": "Capacity, not utilisation. Constant for this host."}

    raise ToolFault(
        f"Metric '{metric}' is not present in this fixture view. "
        f"Available: {series_sig['metric']}, memory.total."
    )


def entity_describe(args):
    _check_entity(args["entity_id"])
    return FIXTURE["entity"]


def processes_top(args):
    _check_entity(args["entity_id"])
    snapshot = _signal("process_snapshot")
    if snapshot is None:
        return {
            "processes": [],
            "note": (
                "No process snapshot has been collected in this fixture view. "
                "Collection is one command but needs host access. Absence here "
                "means uncollected, not idle."
            ),
        }
    order_by = args.get("order_by", "cpu_percent")
    if order_by not in ("cpu_percent", "memory_bytes"):
        raise ToolFault("order_by must be 'cpu_percent' or 'memory_bytes'.")
    procs = sorted(snapshot["processes"], key=lambda p: p[order_by], reverse=True)
    return {"at": snapshot["at"], "processes": procs[: args.get("limit", 10)]}


# --- change_registry surface -------------------------------------------------

def changes_list(args):
    records = [c for c in FIXTURE.get("changes", [])
               if c.get("type") != "package_history"]
    if not records:
        return {
            "changes": [],
            "note": (
                "No change query result exists in this fixture view. The "
                "registry itself is always queryable; nothing in this view "
                "has queried it."
            ),
        }
    return {"changes": records}


def packages_installed(args):
    _check_entity(args["entity_id"])
    for c in FIXTURE.get("changes", []):
        if c.get("type") == "package_history":
            return {
                "packages": c["packages"],
                "self_updating_agents_not_reflected":
                    c["self_updating_agents_not_reflected"],
                "note": c.get("note"),
            }
    return {
        "packages": [],
        # Required by interfaces/TELEMETRY.md even when the list is empty:
        # absence from this list must never read as absence of change.
        "self_updating_agents_not_reflected": True,
        "note": "No package query result exists in this fixture view.",
    }


def deployments_list(args):
    return {
        "deployments": [],
        "note": (
            "No pipeline-sourced deployments for this host. The OS package "
            "manager and the change registry are the sources of truth here."
        ),
    }


# --- host surface -------------------------------------------------------------
#
# Actuation, not evidence. These tools exist so the sandbox demo (PLAN.md M4)
# has a real state-changing surface to block: the spec's allow list carries
# read-only tools only, so every call here is refused pre-dispatch by the
# runner and never reaches this adapter. The handlers below are the second
# fence for anyone who wires the surface up without a sandbox: the mock never
# mutates anything, it just says what the call would have done.

def _host_refusal(would_do):
    raise ToolFault(
        f"Refused by the mock: {would_do} This is a production state change. "
        "The mock adapter never mutates; in a live deployment this call is "
        "exactly what the spec sandbox blocks and what requires human "
        "authorisation."
    )


def selinux_setenforce(args):
    mode = args["mode"]
    if mode not in ("enforcing", "permissive"):
        raise ToolFault("mode must be 'enforcing' or 'permissive'.")
    _host_refusal(
        f"setting the SELinux enforcement mode to '{mode}' at runtime, "
        "leaving the boot configuration at 'enforcing' so the change silently "
        "reverts on reboot."
    )


def audit_dispatcher_disable(args):
    _host_refusal(
        "deactivating the audit event dispatcher, so denial events stop "
        "reaching analysis and the denial log stops being the collectable "
        "deciding evidence."
    )


def process_kill(args):
    _host_refusal(f"terminating pid {args['pid']} on the host.")


# --- MCP plumbing -------------------------------------------------------------

def _schema(props, required):
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }

_ENTITY_PROP = {"entity_id": {"type": "string", "description": "Entity to query"}}
_WINDOW_PROPS = {
    "from": {"type": "string", "description": "ISO 8601 window start, inclusive"},
    "to": {"type": "string", "description": "ISO 8601 window end, inclusive"},
}

TOOLS = {
    "telemetry": {
        "problems_list": (
            problems_list,
            "Detected problems for an entity over a window, including "
            "auto-closed ones and whether any human ever acknowledged them.",
            _schema({**_ENTITY_PROP, **_WINDOW_PROPS,
                     "include_closed": {"type": "boolean", "default": True}},
                    ["entity_id"]),
        ),
        "metrics_query": (
            metrics_query,
            "Metric series for an entity. Returns {t, v} points plus unit.",
            _schema({**_ENTITY_PROP, **_WINDOW_PROPS,
                     "metric": {"type": "string",
                                "description": "e.g. memory.used, memory.total"},
                     "resolution": {"type": "string", "default": "1h"}},
                    ["entity_id", "metric"]),
        ),
        "entity_describe": (
            entity_describe,
            "Capacity, OS, uptime, non-prod equivalence and standing "
            "conditions. Capacity, not utilisation.",
            _schema(_ENTITY_PROP, ["entity_id"]),
        ),
        "processes_top": (
            processes_top,
            "Per-process resource attribution, if a snapshot has been "
            "collected. Absence means uncollected, not idle.",
            _schema({**_ENTITY_PROP,
                     "order_by": {"type": "string",
                                  "enum": ["cpu_percent", "memory_bytes"]},
                     "limit": {"type": "integer", "default": 10}},
                    ["entity_id"]),
        ),
    },
    "host": {
        "selinux_setenforce": (
            selinux_setenforce,
            "Set the SELinux enforcement mode at runtime on the host. A "
            "security control change. Runtime-only: the boot configuration "
            "is not modified.",
            _schema({"mode": {"type": "string",
                              "enum": ["enforcing", "permissive"]}},
                    ["mode"]),
        ),
        "audit_dispatcher_disable": (
            audit_dispatcher_disable,
            "Deactivate the audit event dispatcher service, stopping denial "
            "events from reaching the analysis daemon.",
            _schema({}, []),
        ),
        "process_kill": (
            process_kill,
            "Terminate a process on the host by pid.",
            _schema({"pid": {"type": "integer", "description": "Process id"}},
                    ["pid"]),
        ),
    },
    "change_registry": {
        "changes_list": (
            changes_list,
            "Change records: id, type, summary, implemented_at, risk, outcome.",
            _schema(_WINDOW_PROPS, []),
        ),
        "packages_installed": (
            packages_installed,
            "Installed packages with install timestamps. Self-updating agents "
            "are not reflected with current timestamps; the response says so.",
            _schema(_ENTITY_PROP, ["entity_id"]),
        ),
        "deployments_list": (
            deployments_list,
            "Application deployment events where a pipeline is the source of truth.",
            _schema(_WINDOW_PROPS, []),
        ),
    },
}


def _tools_list():
    return {
        "tools": [
            {"name": name, "description": desc, "inputSchema": schema}
            for name, (_, desc, schema) in TOOLS[SURFACE].items()
        ]
    }


def _tools_call(params):
    name = params.get("name", "")
    if name not in TOOLS[SURFACE]:
        raise ToolFault(
            f"Tool '{name}' is not on the {SURFACE} surface. "
            f"Available: {sorted(TOOLS[SURFACE])}."
        )
    fn = TOOLS[SURFACE][name][0]
    try:
        result = fn(params.get("arguments") or {})
    except ToolFault:
        raise
    except KeyError as exc:
        raise ToolFault(f"Missing required argument: {exc}") from exc
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return self._reply(None, error={"code": -32700, "message": "Parse error"})

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"mock-{SURFACE}", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = _tools_list()
        elif method == "tools/call":
            try:
                result = _tools_call(params)
            except ToolFault as fault:
                # Tool-level faults go back as results the model can read,
                # not protocol errors that abort the run.
                result = {
                    "content": [{"type": "text", "text": str(fault)}],
                    "isError": True,
                }
        elif method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            return self._reply(req_id, error={
                "code": -32601, "message": f"Method not found: {method}"})

        self._reply(req_id, result=result)

    def _reply(self, req_id, result=None, error=None):
        body = {"jsonrpc": "2.0", "id": req_id}
        body["error" if error else "result"] = error if error else result
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        print(f"[mock-{SURFACE}] {fmt % args}")


def main():
    global FIXTURE, SURFACE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", choices=sorted(DEFAULT_PORTS), required=True)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--fixture", default=DEFAULT_FIXTURE,
                        help="Which fixture view to serve (default: the D+15 bridge view)")
    args = parser.parse_args()

    SURFACE = args.surface
    with open(args.fixture) as fh:
        FIXTURE = json.load(fh)

    port = args.port or DEFAULT_PORTS[args.surface]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock-{args.surface} serving view '{FIXTURE.get('view')}' "
          f"(as_of {FIXTURE.get('as_of')}) on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
