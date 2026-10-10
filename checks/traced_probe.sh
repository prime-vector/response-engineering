#!/usr/bin/env bash
# Drive demos/traced.sh without a model, a key or the real demo drivers: does
# it route each mode to the right driver with the right expectations, bring
# the sink up and down around the run, set the exporter environment the way
# the docs say, and propagate the three exit statuses in the order it claims?
#
#   checks/traced_probe.sh
#
# Costs nothing, which is the point: the routing was checked by hand once on
# 8 Oct 2026 and nothing in CI ran it after that, so a dropped --expect or a
# swapped exit test would have shipped green. The script under test is the
# real demos/traced.sh, reached through a symlink in a disposable tree that
# keeps its relative paths; only the two drivers and oa are stubs, and the
# real retry wrapper, sink, stage check, indicators and report run as
# themselves. A stub python3 on the stubs' PATH does one extra thing: it looks
# at the sink's port the moment the stage check is invoked, which is the only
# place a missing cleanup-before-check can be seen, since the EXIT trap would
# close the port before any observation made after return.
set -euo pipefail
cd "$(dirname "$0")/.."
OA_PYTHON=$(sed -n '1s|^#! *||p' "$(command -v oa)")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export WORK OA_PYTHON
"$OA_PYTHON" - <<'PY'
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys

root = Path.cwd()
work = Path(os.environ['WORK'])
interpreter = os.environ['OA_PYTHON']
base = work / 'tree'
for folder in ('demos', 'checks', 'bin'):
    (base / folder).mkdir(parents=True)
for name in ('demos/traced.sh', 'demos/retry.sh', 'demos/agent_traces_sink.py',
             'demos/agent_traces_report.py', 'checks/agent_traces.py',
             'checks/agent_traces_sli.py'):
    (base / name).symlink_to(root / name)

stub = '''import json, os, sys, time, urllib.request
from pathlib import Path
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
case = Path(os.environ['PROBE_CASE'])
with (case / 'oa-arguments').open('a') as out:
    out.write(json.dumps(sys.argv[1:]) + '\\n')
counter = case / 'attempt'
number = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(number))
lines = [s for s in (case / 'scenario').read_text().splitlines() if not s.startswith('status ')]
line = lines[number - 1]
blocked = line.endswith(':blocked')
if blocked: line = line[:-8]
key, verdict = line.split('=')
spec, task, override = key.split(':')
assert sys.argv[1:4] == ['run', '--task', task], sys.argv
if '--telemetry' in sys.argv and os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT'):
    request = ExportTraceServiceRequest()
    scope = request.resource_spans.add().scope_spans.add()
    start = time.time_ns()
    def span(name, ident, parent, attrs, status=1):
        s = scope.spans.add()
        s.trace_id = number.to_bytes(16, 'big')
        s.span_id = ident.to_bytes(8, 'big')
        s.parent_span_id = parent.to_bytes(8, 'big') if parent else b''
        s.name, s.status.code = name, status
        s.start_time_unix_nano, s.end_time_unix_nano = start, start + 10_000_000
        for key, value in attrs.items():
            a = s.attributes.add(key=key)
            setattr(a.value, 'int_value' if type(value) is int else 'string_value', value)
    span('invoke_agent ' + spec, 1, 0, {
        'oa.spec.name': spec, 'oa.task.name': task, 'oa.prompt.override': override,
        'oa.conformance.status': verdict,
        'oa.conformance.reason': 'sandbox_tool_violation' if blocked else ''})
    span('chat claude-fixture', 2, 1, {'gen_ai.operation.name': 'chat',
        'gen_ai.request.model': 'claude-fixture', 'gen_ai.usage.input_tokens': 12,
        'gen_ai.usage.output_tokens': 3})
    if blocked:
        span('oa.sandbox.decision', 3, 1, {'oa.sandbox.result': 'blocked'})
        span('execute_tool selinux_setenforce', 4, 1, {
            'gen_ai.tool.name': 'selinux_setenforce', 'oa.tool.result': 'blocked'}, 2)
    req = urllib.request.Request(os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] + '/v1/traces',
        data=request.SerializeToString(), headers={'Content-Type': 'application/x-protobuf'})
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
'''
(base / 'bin/oa').write_text('#!' + interpreter + '\n' + stub)
# The sink must run directly under oa's interpreter: killing a re-exec parent
# would leave its child listening. The observer also tests the flush barrier
# at check time, before the EXIT trap could conceal a missing cleanup.
(base / 'bin/python3').write_text('#!' + interpreter + '\n' + '''import os, socket, sys
from pathlib import Path
if sys.argv[1] == 'checks/agent_traces.py':
    case = Path(os.environ['PROBE_CASE'])
    port = int(Path(sys.argv[2]).with_name('ready').read_text())
    with socket.socket() as connection:
        connection.settimeout(1)
        alive = connection.connect_ex(('127.0.0.1', port)) == 0
    (case / 'sink-at-check').write_text('open' if alive else 'closed')
os.execv(os.environ['OA_PYTHON'], [os.environ['OA_PYTHON'], *sys.argv[1:]])
''')
driver = '''#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'RECORD'
import json, os, sys
from pathlib import Path
names = ('ENDPOINT', 'TRACES_ENDPOINT', 'PROTOCOL', 'TRACES_PROTOCOL', 'HEADERS', 'TRACES_HEADERS')
Path(os.environ['PROBE_CASE'], 'driver.json').write_text(json.dumps({
    'driver': sys.argv[0], 'args': sys.argv[1:],
    'env': {n: os.environ.get('OTEL_EXPORTER_OTLP_' + n) for n in names}}))
RECORD
printf '%s' "$0" > "$PROBE_CASE/driver-name"
OA_MARKS="$PROBE_CASE/marks"
OA_LOG_GLOB="$PROBE_CASE/adapter-*.log"
. demos/retry.sh
while IFS= read -r stage; do
  case "$stage" in
    'status '*) exit "${stage#status }" ;;
    *) task=${stage#*:}; task=${task%%:*}; oa_run --task "$task" ;;
  esac
done < "$PROBE_CASE/scenario"
'''
for name in ('governance', 'investigate'):
    (base / f'demos/{name}.sh').write_text(driver)
for name in ('oa', 'python3'):
    (base / 'bin' / name).chmod(0o755)

failures = 0
checks = 0
def check(name, good, detail=''):
    global failures, checks
    checks += 1
    print(f"  {'ok' if good else 'FAIL'} {name}" + (f': {detail}' if not good else ''), flush=True)
    failures += not good

def contains(name, path, text):
    check(name, path.exists() and text in path.read_text(), text)

def closed(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) != 0

serial = 0
def run(args, stages, status=0, remote=False, replacement=None):
    global serial
    serial += 1
    case = work / str(serial)
    case.mkdir()
    # Copies preserve symlinks so every normal case still runs the real files.
    import shutil
    tree = case / 'tree'
    shutil.copytree(base, tree, symlinks=True)
    (case / 'scenario').write_text('\n'.join([*stages, f'status {status}']) + '\n')
    if replacement:
        path, content = replacement
        target = tree / path
        target.unlink()
        target.write_text(content)
    env = dict(os.environ, PROBE_CASE=str(case), PATH=str(tree / 'bin') + os.pathsep + os.environ['PATH'])
    for name in ('ENDPOINT', 'TRACES_ENDPOINT', 'PROTOCOL', 'TRACES_PROTOCOL', 'HEADERS', 'TRACES_HEADERS'):
        env.pop('OTEL_EXPORTER_OTLP_' + name, None)
    if remote:
        env.update(OTEL_EXPORTER_OTLP_TRACES_ENDPOINT='http://example.invalid/v1/traces',
                   OTEL_EXPORTER_OTLP_HEADERS='fixture=value', OTEL_EXPORTER_OTLP_TRACES_HEADERS='fixture=value')
    # A broken cleanup mutation can leave a listener behind. Observe it
    # before reclaiming the case's process group, so disposal cannot hide it.
    process = subprocess.Popen(['bash', str(tree / 'demos/traced.sh'), *args], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
        result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        ready = list((tree / 'runs').glob('*/ready'))
        if ready:
            (case / 'sink-after-return').write_text(
                'closed' if closed(int(ready[0].read_text())) else 'open')
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.communicate()
    (case / 'stdout').write_text(result.stdout)
    (case / 'stderr').write_text(result.stderr)
    dirs = list((tree / 'runs').glob('*')) if (tree / 'runs').exists() else []
    return case, tree, dirs[0] if dirs else None, result

sandbox = 'incident-commander:mitigate:none=violation_prevented:blocked'
# Validate the generated shape before mode tests, since a report failure must
# not masquerade as evidence that an expectation rejected a missing stage.
case, tree, output, result = run(['sandbox'], [sandbox])
check('fixture export accepted end to end', result.returncode == 0, result.stderr + result.stdout)
if output is None:
    sys.exit('FAIL: fixture produced no run directory')
for command in ([sys.executable, str(root / 'checks/agent_traces_sli.py'), str(output / 'spans.jsonl'), '-o', str(case / 'fixture.json')],
                [sys.executable, str(root / 'demos/agent_traces_report.py'), str(case / 'fixture.json')]):
    validation = subprocess.run(command, capture_output=True, text=True)
    check('fixture accepted by ' + Path(command[1]).name, validation.returncode == 0, validation.stderr)

def clean_assertions(case, output, result, label):
    check(label + ' exit', result.returncode == 0, result.stdout + result.stderr)
    check(label + ' summary', 'driver=0, check=0, report=0' in result.stdout)
    for name in ('spans.jsonl', 'check.log', 'status', 'sli.json', 'report.html'):
        check(label + ' artefact ' + name, (output / name).is_file())
    spans = [json.loads(s) for s in (output / 'spans.jsonl').read_text().splitlines()]
    check(label + ' one trace', len({s['trace_id'] for s in spans}) == 1)
    contains(label + ' stage summary', output / 'check.log', 'incident-commander:mitigate:none [trace')
    contains(label + ' blocked tool', output / 'check.log', 'tools=selinux_setenforce=blocked')
    check(label + ' status record', (output / 'status').read_text() == 'driver=0\ncheck=0\n')
    record = json.loads((case / 'driver.json').read_text())
    check(label + ' driver args', record['args'] == ['sandbox'])
    values = record['env']
    check(label + ' local endpoint', bool(re.fullmatch(r'http://127\.0\.0\.1:\d+', values['ENDPOINT'] or '')))
    check(label + ' protobuf protocols', values['PROTOCOL'] == values['TRACES_PROTOCOL'] == 'http/protobuf')
    check(label + ' destinations and headers cleared', all(values[n] is None for n in ('TRACES_ENDPOINT', 'HEADERS', 'TRACES_HEADERS')))
    calls = [json.loads(s) for s in (case / 'oa-arguments').read_text().splitlines()]
    check(label + ' oa arguments', calls == [['run', '--task', 'mitigate', '--telemetry']])
    check(label + ' sink closed before check', (case / 'sink-at-check').read_text() == 'closed')
    check(label + ' sink closed after return', (case / 'sink-after-return').read_text() == 'closed')

clean_assertions(case, output, result, 'clean sandbox')
case, tree, output, result = run(['sandbox'], [sandbox], remote=True)
clean_assertions(case, output, result, 'inherited remote')

contract = 'incident-commander:assess:system=nonconformant'
attribution = ['incident-commander:assess:none=conformant', contract]
grounding = ['precedent-analyst:recall:none=conformant', 'precedent-analyst:recall:system=nonconformant']
act1 = ['telemetry-analyst:detect:none=conformant', grounding[0]]
act2 = ['change-correlator:correlate:none=conformant', attribution[0]]
act3 = ['scribe:timeline:none=conformant']
modes = [(['sandbox'], [sandbox]), (['contract'], [contract]), (['attribution'], attribution),
         (['grounding'], grounding), (['refusal'], grounding[:1]),
         (['all'], [sandbox, contract, *attribution, *grounding, grounding[0]])]
modes += [(['investigate', act], stages) for act, stages in
          [('act1', act1), ('act2', act2), ('act3', act3), ('all', act1 + act2 + act3)]]
modes += [(['investigate'], act1 + act2 + act3), ([], [sandbox, contract, *attribution, *grounding, grounding[0]])]
for args, stages in modes:
    label = ' '.join(args) or 'default all'
    case, tree, output, result = run(args, stages)
    check(label + ' routing passes', result.returncode == 0, result.stdout + result.stderr)
    expected_args = args[1:] if args and args[0] == 'investigate' else args or ['all']
    expected_driver = 'investigate' if args and args[0] == 'investigate' else 'governance'
    check(label + ' driver routing', (case / 'driver-name').read_text() == f'demos/{expected_driver}.sh')
    check(label + ' driver arguments', json.loads((case / 'driver.json').read_text())['args'] == expected_args)
    for index, stage in enumerate(stages):
        remaining = stages[:index] + stages[index + 1:]
        # Single-stage modes need an unrelated valid trace to isolate missing
        # expectations from the reader's separate empty-file rejection.
        case, tree, output, result = run(args, remaining or ['fixture:unrelated:none=conformant'])
        key, verdict = stage.removesuffix(':blocked').split('=')
        count = sum(s.removesuffix(':blocked') == stage.removesuffix(':blocked') for s in stages)
        reason = (f'{key}: expected stage missing' if count == 1 else
                  f'{key}: expected {count} {verdict} stage(s), found {count - 1}')
        check(label + ' missing ' + key + ' exit', result.returncode == 1, result.stdout + result.stderr)
        contains(label + ' missing ' + key + ' reason', output / 'check.log', reason)

for driver_status, passing in ((3, True), (3, False), (0, False)):
    case, tree, output, result = run(['sandbox'], [sandbox] if passing else ['fixture:unrelated:none=conformant'], driver_status)
    expected_check = 0 if passing else 1
    label = f'precedence driver={driver_status} check={expected_check}'
    check(label + ' exit', result.returncode == (driver_status or expected_check))
    check(label + ' summary', f'driver={driver_status}, check={expected_check}, report=0' in result.stdout)
    contains(label + ' check evidence', output / 'check.log', 'verdict=violation_prevented' if passing else 'incident-commander:mitigate:none: expected stage missing')
report_broken = ('checks/agent_traces_sli.py', 'raise SystemExit(7)\n')
case, tree, output, result = run(['sandbox'], [sandbox], replacement=report_broken)
check('report failure exit', result.returncode == 7)
check('report failure summary', 'driver=0, check=0, report=7' in result.stdout)
contains('report failure preserves check', output / 'check.log', 'verdict=violation_prevented')
# Report last, held pairwise. With the report the only non-zero status, the
# cases above pass whichever order the wrapper tests in; the order is only
# pinned when two statuses are non-zero at once and the assertion names
# which one wins.
case, tree, output, result = run(['sandbox'], ['fixture:unrelated:none=conformant'], replacement=report_broken)
check('check beats report exit', result.returncode == 1, result.stdout + result.stderr)
check('check beats report summary', 'driver=0, check=1, report=7' in result.stdout)
case, tree, output, result = run(['sandbox'], [sandbox], 3, replacement=report_broken)
check('driver beats report exit', result.returncode == 3, result.stdout + result.stderr)
check('driver beats report summary', 'driver=3, check=0, report=7' in result.stdout)
for args in (['unknown'], ['investigate', 'bogus']):
    case, tree, output, result = run(args, [])
    check('usage ' + ' '.join(args) + ' exit', result.returncode == 2)
    check('usage ' + ' '.join(args) + ' reason', 'Usage: demos/traced.sh' in result.stderr)
    check('usage ' + ' '.join(args) + ' creates no runs', not (tree / 'runs').exists())
for label, content, reason in [('sink crash', "import sys\nprint('boom', file=sys.stderr)\nraise SystemExit(1)\n", 'boom'),
                               ('sink readiness timeout', 'import time\ntime.sleep(60)\n', 'did not become ready')]:
    case, tree, output, result = run(['sandbox'], [sandbox], replacement=('demos/agent_traces_sink.py', content))
    check(label + ' exit', result.returncode == 1)
    check(label + ' reason', reason in result.stderr, result.stderr)
    check(label + ' driver never started', not (case / 'driver.json').exists())
print(f'Traced probe: {checks} checks, {failures} failures.')
sys.exit(bool(failures))
PY
