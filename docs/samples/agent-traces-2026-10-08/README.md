# Two traced runs, their indicators, and the pages rendered from them

Both span files are from the agent traces acceptance run on 8 Oct 2026, on OA
1.6.2 with `claude-sonnet-4-6`. `governance-all` is `./demos/traced.sh all`,
the five governance demos in one run: seven stages, including the blocked
`selinux_setenforce` call ending `violation_prevented`. `investigate` is
`./demos/traced.sh investigate`, the three acts composed: five stages, each
conformant, and a driver that failed anyway.

## What is in each directory

| File | What it is | Where it came from |
| --- | --- | --- |
| `spans.jsonl` | the span metadata the local sink received, one span per line, byte for byte | the live run |
| `status` | `driver=N` and `check=N`, the two exit statuses the wrapper recorded | the live run's output, as recorded on the task board the same day; the wrapper did not yet write this file |
| `check.log` | what `checks/agent_traces.py` printed for this run | re-run on the committed spans with the expectations `demos/traced.sh` sets for that mode; the check is deterministic |
| `sli.json` | the stage attempts and indicators `checks/agent_traces_sli.py` computed | generated from the three files above |
| `report.html` | the page `demos/agent_traces_report.py` rendered from `sli.json` | generated |

`baseline.json` is `--aggregate` over both `sli.json` files: a baseline of two
runs, which is enough to show the shape and not enough to set a target from.

## Why the investigate run is committed with a failing driver

Every stage in it is conformant, every tool span succeeded, and the stage
check passed. The driver failed in `checks/timeline_filed.py`: the Scribe's
reply hashed differently from the payload its one successful `record_update`
filed. That is the split this whole feature rests on. A span proves that the
call was made and did not raise; what it carried is in the adapter log, and
only the driver checks it. A page that showed only the span side of that run
would say everything was fine. This one shows `stage check: pass` beside
`driver: fail`, and that pairing is the point.

## Regenerating

Re-running these writes nothing if the artefacts are current, and CI checks
that they are. From the repository root:

```bash
for run in governance-all investigate; do
  d=docs/samples/agent-traces-2026-10-08/$run
  python3 checks/agent_traces_sli.py "$d/spans.jsonl" --status-file "$d/status" \
    --check-output "$d/check.log" -o "$d/sli.json"
  python3 demos/agent_traces_report.py "$d/sli.json"
done
python3 checks/agent_traces_sli.py --aggregate \
  docs/samples/agent-traces-2026-10-08/*/sli.json \
  -o docs/samples/agent-traces-2026-10-08/baseline.json
```
