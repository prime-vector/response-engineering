"""Offline regressions for accepted writes, time-bounded scores and provenance."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from checks.timeline_filed import verify
from corpus import ingest
from mock import adapter

ROOT = Path(__file__).resolve().parents[1]


class EvidenceControls(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((ROOT / 'corpus/index.json').read_text())
        adapter.INDEX = copy.deepcopy(self.index)
        adapter.FIXTURE = json.loads((ROOT / 'fixtures/composite-incident.json').read_text())
        adapter.SURFACE = 'incident_record'
        self.output = {'entries': [{'event': 'synthetic event'}], 'gaps': [],
                       'record_ref': 'synthetic-record', 'record_updated': True}

    def receipt(self):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            adapter._tools_call({'name': 'record_update', 'arguments': {
                'record_ref': self.output['record_ref'],
                'update': {k: self.output[k] for k in ('entries', 'gaps')}}})
        return log.getvalue()

    def test_receipt_matches_content_and_reference_without_logging_text(self):
        log = self.receipt()
        verify(self.output, log)
        self.assertNotIn('synthetic event', log)
        for key, value in [('record_ref', 'other'), ('entries', []), ('gaps', ['missing'])]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'matches record_ref' if key == 'record_ref' else 'payload differs'):
                verify({**self.output, key: value}, log)
        with self.assertRaisesRegex(ValueError, 'successful filing and record_ref'):
            verify({**self.output, 'record_updated': False}, log)
        with self.assertRaisesRegex(ValueError, 'successful filing and record_ref'):
            verify({**self.output, 'record_ref': ''}, log)
        with self.assertRaisesRegex(ValueError, 'No successful record_update receipt'):
            verify(self.output, log.replace('"record_update"', '"record_create"'))

    def test_refused_write_or_call_attempt_does_not_prove_filing(self):
        log = io.StringIO()
        with contextlib.redirect_stdout(log), self.assertRaisesRegex(adapter.ToolFault, 'Refused'):
            adapter._tools_call({'name': 'record_update', 'arguments': {
                'record_ref': 'synthetic-record', 'update': {}, 'submit': True}})
        self.assertNotIn('receipt ', log.getvalue())
        with self.assertRaisesRegex(ValueError, 'No successful record_update receipt'):
            verify(self.output, '[mock-incident_record] tools/call record_update\n' + log.getvalue())

    def test_nonaccepted_result_emits_no_receipt(self):
        fn, description, schema = adapter.TOOLS['incident_record']['record_update']
        replacement = (lambda args: {'accepted': False, 'record_ref': args['record_ref']}, description, schema)
        with patch.dict(adapter.TOOLS['incident_record'], {'record_update': replacement}):
            self.assertNotIn('receipt ', self.receipt())

    def test_attempt_window_excludes_earlier_matching_receipt(self):
        receipt = self.receipt()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'sink.log'
            log.write_text(receipt)
            env = {**os.environ, 'OA_MARKS': str(Path(directory) / 'marks'),
                   'OA_LOG_GLOB': str(log)}
            # These are the same window functions used around oa_run_once in act3.
            command = '. demos/retry.sh; mark_logs; attempt_log "$1"'
            old = subprocess.check_output(['bash', '-c', command, 'test', str(log)],
                                          cwd=ROOT, env=env, text=True)
            with self.assertRaisesRegex(ValueError, 'No successful record_update receipt'):
                verify(self.output, old)
            with log.open('a') as handle:
                handle.write(receipt)
            current = subprocess.check_output(
                ['bash', '-c', '. demos/retry.sh; attempt_log "$1"', 'test', str(log)],
                cwd=ROOT, env=env, text=True)
            verify(self.output, current)

    def test_verifier_cli_reports_missing_input_without_traceback(self):
        for args in ([], ['does-not-exist.json', 'does-not-exist.log']):
            result = subprocess.run([sys.executable, 'checks/timeline_filed.py', *args],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FAIL:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_future_documents_do_not_change_historical_hits_or_scores(self):
        bound = json.loads((ROOT / 'fixtures/composite-incident.d1.json').read_text())['as_of']
        for path in ('corpus/index.json', 'corpus/index.fixed.json'):
            with self.subTest(index=path):
                index = json.loads((ROOT / path).read_text())
                visible = [p for p in index['passages'] if p['recorded_at'] <= bound[:10]]
                self.assertLess(len(visible), len(index['passages']))
                args = {'symptom_text': 'audit denial log naming source domain outstanding', 'before': bound}
                adapter.INDEX = {**index, 'passages': visible}
                historical = adapter.precedent_search(args)
                adapter.INDEX = copy.deepcopy(index)
                # Warm a later query too: no global cache may contaminate the early one.
                adapter.precedent_search({**args, 'before': '2026-03-31'})
                replay = adapter.precedent_search(args)
                self.assertTrue(historical['passages'])
                for key in ('passages', 'cleared_floor', 'total_scoring_above_zero', 'candidates_considered'):
                    self.assertEqual(historical[key], replay[key], key)
                self.assertGreater(replay['excluded_by_before'], historical['excluded_by_before'])

    def test_future_vocabulary_does_not_change_floor_decision(self):
        old = copy.deepcopy(self.index['passages'][0])
        old.update(text='alpha', heading_path='alpha', recorded_at='2025-01-01')
        future = {**old, 'passage_id': 'future', 'text': 'beta gamma', 'heading_path': 'beta gamma',
                  'recorded_at': '2027-01-01'}
        args = {'symptom_text': 'alpha beta gamma', 'before': '2026-03-03'}
        adapter.INDEX = {'passages': [old]}
        expected = adapter.precedent_search(args)
        self.assertEqual(expected['passages'], [])  # Score is below the existing 0.35 floor.
        adapter.INDEX = {'passages': [old, future, {**future, 'passage_id': 'future-2'}]}
        self.assertEqual(adapter.precedent_search(args)['passages'], [])

    def test_empty_historical_archive_returns_no_hits(self):
        result = adapter.precedent_search({'symptom_text': 'memory', 'before': '1900-01-01'})
        self.assertEqual(result['candidates_considered'], 0)
        self.assertEqual(result['passages'], [])

    def test_manifest_is_checked_and_repaired_without_rewriting_index(self):
        index = ingest.build('heading')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'index.json'
            manifest = Path(directory) / 'manifest.yaml'
            target.write_text(json.dumps(index, indent=2) + '\n')
            before = target.stat().st_mtime_ns
            with patch.object(ingest, 'INDEXES', {'heading': str(target)}), \
                 patch.object(ingest, 'MANIFEST', str(manifest)), contextlib.redirect_stdout(io.StringIO()):
                for content in (None, 'stale provenance'):
                    if content is not None:
                        manifest.write_text(content)
                    with patch('sys.argv', ['ingest', '--check']):
                        self.assertEqual(ingest.main(), 1)
                    self.assertEqual(manifest.read_text() if manifest.exists() else None, content)
                    with patch('sys.argv', ['ingest']):
                        self.assertEqual(ingest.main(), 0)
                    self.assertEqual(manifest.read_text(), ingest.write_manifest(index))
                    self.assertEqual(target.stat().st_mtime_ns, before)
                manifest_mtime = manifest.stat().st_mtime_ns
                with patch('sys.argv', ['ingest', '--check']):
                    self.assertEqual(ingest.main(), 0)
                with patch('sys.argv', ['ingest']):
                    self.assertEqual(ingest.main(), 0)
                self.assertEqual(manifest.stat().st_mtime_ns, manifest_mtime)

    def test_verifier_cli_rejects_nonobject_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'timeline.json'
            log = Path(directory) / 'sink.log'
            for value in ([], None, True, 42, "text"):
                for target in ('timeline', 'receipt'):
                    with self.subTest(value=value, target=target):
                        output.write_text(json.dumps(value if target == 'timeline' else self.output))
                        log.write_text('' if target == 'timeline' else
                                       '[mock-incident_record] receipt ' + json.dumps(value))
                        result = subprocess.run([sys.executable, 'checks/timeline_filed.py',
                                                 str(output), str(log)], cwd=ROOT,
                                                capture_output=True, text=True)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('must be a JSON object', result.stderr)
                        self.assertIn('FAIL:', result.stderr)
                        self.assertNotIn('Traceback', result.stderr)

    def test_payload_mismatch_names_both_digests(self):
        import hashlib
        log = self.receipt()
        changed = {**self.output, 'entries': []}
        expected = hashlib.sha256(json.dumps({'entries': [], 'gaps': []}, sort_keys=True).encode()).hexdigest()
        accepted = json.loads(log.split(' receipt ', 1)[1])['payload_sha256']
        with self.assertRaisesRegex(ValueError, 'payload differs') as raised:
            verify(changed, log)
        self.assertIn(expected, str(raised.exception))
        self.assertIn(accepted, str(raised.exception))
        # An earlier mismatching receipt must not hide a later exact match.
        verify(self.output, log.replace(accepted, 'wrong') + log)

    def test_failed_filing_is_valid_output_but_not_verified_success(self):
        import yaml
        import jsonschema
        spec = yaml.safe_load((ROOT / '.agents/scribe.yaml').read_text())
        output = {'entries': [], 'gaps': [], 'record_ref': '', 'record_updated': False}
        jsonschema.validate(output, spec['tasks']['timeline']['output'])
        self.assertIn('empty string', spec['tasks']['timeline']['output']['properties']['record_ref']['description'])
        self.assertIn('record_ref an empty string', spec['prompts']['system'])
        with self.assertRaisesRegex(ValueError, 'successful filing and record_ref'):
            verify(output, '')

    def test_local_packages_win_over_installed_namesakes(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('mock', 'checks', 'corpus'):
                package = Path(directory) / name
                package.mkdir()
                (package / '__init__.py').write_text('raise RuntimeError("external package imported")')
            subprocess.run([sys.executable, '-c',
                            'from mock import adapter; from checks import timeline_filed; from corpus import ingest'],
                           cwd=ROOT, env={**os.environ, 'PYTHONPATH': directory},
                           capture_output=True, text=True, check=True)
