#!/usr/bin/env python3
"""
Generate the synthetic fixture for the composite scenario.

Everything here is invented. See SCENARIO.md for the sanitisation rules.
The shape is tunable: adjust ONSET, PROBLEM_DAYS and the memory profile to
match the reference chart once it is available.

Two views, because evidence honesty is time-dependent (SCENARIO.md section 4).
Each view contains only what had actually been collected by its `as_of` time,
not what was obtainable. Absence means uncollected, however cheap the
collection would have been. That asymmetry is the scenario.

    python3 fixtures/generate.py > fixtures/composite-incident.json             # D+15, the bridge
    python3 fixtures/generate.py --at d2 > fixtures/composite-incident.d2.json  # act one
"""

import argparse
import json
from datetime import datetime, timedelta, timezone

# Synthetic anchor. D0 is the day the denial storm begins.
# SCENARIO.md fixes D0 as "Monday 2 March": 2026-03-02 is a Monday.
D0 = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc)
CHANGE_DAY = D0 - timedelta(days=8)          # compliance agent rollout
TICKET = D0 + timedelta(days=15, hours=16, minutes=40)
BRIDGE = D0 + timedelta(days=15, hours=17)

VIEWS = {
    # Act one. Third auto-closed occurrence on the board, no ticket, no bridge,
    # nothing collected from the host. The only signal is the feed itself.
    "d2": D0 + timedelta(days=2, hours=9),
    # Acts two and three. Two and a half hours into the bridge: process
    # snapshot taken, change correlation run, deciding evidence requested
    # and still outstanding.
    "d15": BRIDGE + timedelta(hours=2, minutes=30),
}

ENTITY = "intg-prod-a1"
GIB = 1024 ** 3

# 13 problems across 15 days. Two quiet days, because real feeds are not tidy.
PROBLEM_DAYS = [0, 1, 2, 3, 5, 6, 7, 8, 9, 11, 12, 13, 14]

JVM_BYTES = int(23.1 * GIB)
TOTAL_BYTES = 32 * GIB


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def problems(as_of):
    out = []
    for i, day in enumerate(PROBLEM_DAYS):
        opened = D0 + timedelta(days=day, hours=3, minutes=17 + (i * 7) % 40)
        if opened > as_of:
            continue
        closed = opened + timedelta(hours=2, minutes=40)
        still_open = closed > as_of
        out.append({
            "id": f"P-{4100 + i}",
            "title": "Memory exhaustion and elevated page fault rate",
            # Stable signature is what makes recurrence detectable at all.
            "signature": "host.memory.exhaustion:intg-prod-a1",
            "severity": "error",
            "opened_at": iso(opened),
            "closed_at": None if still_open else iso(closed),
            "auto_closed": not still_open,
            "acknowledged_by": None,
            "affected_entities": [ENTITY],
            "root_cause_claimed": None,
        })
    return out


def memory_series(as_of):
    """Hourly. Flat and healthy pre-onset, then sawtooth as the daemon grows
    and is periodically killed by memory pressure."""
    series = []
    for h in range(-72, 16 * 24):
        t = D0 + timedelta(hours=h)
        if t > as_of:
            break
        if h < 0:
            used = JVM_BYTES + int(1.1 * GIB)
        else:
            # Daemon RSS climbs ~0.6 -> 4 GiB over roughly 40 hours, then resets.
            phase = (h % 40) / 40.0
            daemon = (0.6 + phase * 3.4) * GIB
            used = JVM_BYTES + int(1.1 * GIB) + int(daemon)
        series.append({"t": iso(t), "v": min(used, TOTAL_BYTES)})
    return series


def build(view):
    as_of = VIEWS[view]
    at_bridge = view == "d15"
    feed = problems(as_of)

    fixture = {
        "_comment": "Synthetic. Composite scenario, not a client incident. See SCENARIO.md.",

        "view": view,
        "as_of": iso(as_of),

        # No incident exists at D+2. Nothing has been reported, nothing has
        # been declared. That is the point of act one.
        "incident_id": "SYN-0001" if at_bridge else None,
        "elapsed_minutes": (
            int((as_of - TICKET).total_seconds() // 60) if at_bridge else None
        ),
        "symptom": (
            "Scheduled batch file transfers completing late. Business user reports "
            "the integration console is slow to respond. No transfers have failed."
        ) if at_bridge else None,

        "entity": {
            "entity_id": ENTITY,
            "type": "host",
            "environment": "production",
            "capacity": {
                "cpu_cores": 8,
                "memory_bytes": TOTAL_BYTES,
                "swap_bytes": 8 * GIB,
            },
            "os": {
                "family": "rhel",
                "version": "8.x",
                "security_module": "selinux",
                "mode": "enforcing",
            },
            "uptime_seconds": 247 * 86400,
            "non_prod_equivalent": {
                "entity_id": "intg-nonprod-a1",
                "build_parity": False,
                "note": "Different patch level and a different set of installed agents.",
            },
            "standing_conditions": [
                {
                    "description": (
                        "Integration service JVM holds 23.1 GiB resident of 32 GiB "
                        "total. Steady state for at least 6 months."
                    ),
                    "alerting": False,
                    "owner": None,
                }
            ],
        },

        "signals": [
            {
                "source": "observability_platform",
                "type": "problem_feed",
                # Window opens before onset so a consumer can see the feed was
                # quiet until D0.
                "window": {"from": iso(D0 - timedelta(hours=72)), "to": iso(as_of)},
                "problems": feed,
                "total": len(feed),
                "unacknowledged": len(feed),
                "note": "No problem in this window was acknowledged, assigned or actioned.",
            },
            {
                "source": "observability_platform",
                "type": "metric_series",
                "metric": "memory.used",
                "unit": "bytes",
                "resolution": "1h",
                "series": memory_series(as_of),
            },
        ],

        # Deliberately thin. This is the constraint that keeps the demo honest:
        # the deciding evidence was never collected, so the agent cannot use it.
        "evidence": [],

        # Empty at D+2: nobody has hypothesised anything yet, so naming the
        # deciding evidence here would leak insight backwards in time.
        "missing_evidence": [],

        # Absence means no query has been run, not that the registry is empty.
        # The registry was queryable throughout; nobody looked until D+15.
        "changes": [],

        "prior_hypotheses": [],
    }

    if at_bridge:
        fixture["signals"].append({
            "source": "host",
            "type": "process_snapshot",
            "at": iso(BRIDGE + timedelta(hours=2)),
            "processes": [
                {
                    "pid": 3501048,
                    "user": "audit-analysis",
                    "command": "/usr/libexec/platform-python -Es /usr/sbin/setroubleshootd -f",
                    "cpu_percent": 99.7,
                    "memory_bytes": int(0.58 * GIB),
                    "started_at": iso(D0 + timedelta(hours=6)),
                    "cumulative_cpu_time": "79:58",
                },
                {
                    "pid": 3489339,
                    "user": "intgsvc",
                    "command": "java -jar integration-service.jar",
                    "cpu_percent": 5.6,
                    "memory_bytes": JVM_BYTES,
                    "started_at": iso(D0 - timedelta(days=180)),
                    "cumulative_cpu_time": "12878:17",
                },
            ],
        })

        fixture["evidence"] = [
            {
                "id": "E-1",
                "description": (
                    "Process listing confirms the audit analysis daemon is active "
                    "and consuming CPU. Does not identify what is generating the "
                    "denials it is processing."
                ),
                "collected_at": iso(BRIDGE + timedelta(hours=2)),
                "establishes": "daemon is active",
                "does_not_establish": "source of the denials",
            },
            {
                "id": "E-2",
                "description": (
                    "Security module confirmed in enforcing mode. Denials are real "
                    "and are being logged."
                ),
                "collected_at": iso(BRIDGE + timedelta(hours=2, minutes=20)),
            },
        ]

        fixture["missing_evidence"] = [
            {
                "description": (
                    "Audit denial log for the affected window, showing the source "
                    "domain and denied action for each denial."
                ),
                "how_to_obtain": "Query the audit log for denial records over the last 14 days on the affected host.",
                "requested_from": "platform_team",
                "requested_at": iso(BRIDGE + timedelta(hours=2, minutes=21)),
                "still_outstanding": True,
                "note": "This is the deciding evidence. Everything else is inference until it lands.",
            }
        ]

        fixture["changes"] = [
            {
                "id": "CHG-88104",
                "type": "agent_deployment",
                "summary": "Endpoint compliance agent 7.4.2 rolled out to server fleet",
                "implemented_at": iso(CHANGE_DAY),
                "risk": "low",
                "outcome": "successful",
                "implementer_role": "security_engineering",
            },
            {
                "id": "PKG-list",
                "type": "package_history",
                "queried_at": iso(BRIDGE + timedelta(hours=2, minutes=21)),
                "self_updating_agents_not_reflected": True,
                "packages": [
                    {"name": "endpoint-compliance-agent", "version": "7.4.2-27",
                     "installed_at": iso(CHANGE_DAY)},
                    {"name": "audit-analysis-server", "version": "3.3.22-2.el8",
                     "installed_at": iso(D0 - timedelta(days=1085))},
                    {"name": "kernel", "version": "4.18.0",
                     "installed_at": iso(D0 - timedelta(days=192))},
                ],
                "note": (
                    "The audit analysis daemon has been installed for 3 years. Its "
                    "activation is not an installation event. The newest package on "
                    "the host predates onset by 8 days."
                ),
            },
        ]

    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", choices=sorted(VIEWS), default="d15",
                        help="Which point in time the view represents (default: d15)")
    args = parser.parse_args()
    print(json.dumps(build(args.at), indent=2))


if __name__ == "__main__":
    main()
