"""Invalid inputs must return explainable tool faults or JSON-RPC errors."""
import contextlib
import http.client
import io
import json
from pathlib import Path
import threading
import unittest

from mock import adapter


class Arguments(unittest.TestCase):
    def setUp(self):
        adapter.INDEX = json.loads(Path('corpus/index.json').read_text())
        adapter.FIXTURE = json.loads(Path('fixtures/composite-incident.json').read_text())

    def test_invalid_arguments_are_refused_for_the_expected_reason(self):
        cases = [
            ('telemetry', 'entity_describe', {'entity_id': 5}, 'entity_id must be string'),
            ('telemetry', 'processes_top', {'entity_id': 'x', 'limit': 0}, 'limit must be at least 1'),
            ('telemetry', 'problems_list', {'entity_id': 'x', 'include_closed': 'yes'}, 'include_closed must be boolean'),
            ('telemetry', 'problems_list', {'entity_id': 'x', 'from': 'yesterday'}, 'from must be an ISO'),
            ('change_registry', 'changes_list', {'from': '2026-04-01', 'to': '2026-03-01'}, 'from must not be after to'),
            ('change_registry', 'changes_list', {'to': '2026-02-30'}, 'to must be an ISO'),
            ('change_registry', 'packages_installed', [], 'arguments must be object'),
            ('host', 'process_kill', {'pid': True}, 'pid must be integer'),
            ('host', 'selinux_setenforce', {'mode': 'anything'}, 'mode must be one of'),
            ('incident_record', 'record_update', {'record_ref': 'r'}, 'update is required'),
            ('incident_record', 'record_update', {'record_ref': 'r', 'update': []}, 'update must be object'),
            ('precedent_archive', 'precedent_search', {'before': '2026-03-03', 'limit': 'abc'}, 'limit must be integer'),
            ('precedent_archive', 'precedent_search', {'before': '2026-03-03', 'limit': -1}, 'limit must be at least 1'),
            ('precedent_archive', 'precedent_search', {'before': '2026-03-03', 'signature_terms': 'memory'}, 'signature_terms must be array'),
            ('precedent_archive', 'precedent_search', {'before': '2026-03-03', 'signature_terms': [1]}, r'signature_terms\[0\] must be string'),
            ('precedent_archive', 'coverage_describe', {}, 'before is required'),
            ('precedent_archive', 'coverage_describe', {'before': 'not-a-date'}, 'before must be an ISO'),
            ('precedent_archive', 'precedent_search', {'before': '2026-02-30', 'symptom_text': 'memory'}, 'before must be an ISO'),
        ]
        for surface, name, args, reason in cases:
            with self.subTest(tool=name, args=args), self.assertRaisesRegex(adapter.ToolFault, reason):
                adapter.SURFACE = surface
                adapter._tools_call({'name': name, 'arguments': args})

    def test_declared_enum_values_and_near_misses(self):
        for surface in adapter.TOOLS.values():
            for _, _, schema in surface.values():
                for prop in schema['properties'].values():
                    if 'enum' not in prop:
                        continue
                    for value in prop['enum']:
                        adapter._validate(value, prop)
                        with self.assertRaisesRegex(adapter.ToolFault, 'must be one of'):
                            adapter._validate(value.upper(), prop)

    def test_unknown_schema_types_fault_explicitly(self):
        for kind in ('number', 'null', ['string', 'null']):
            with self.subTest(kind=kind), self.assertRaisesRegex(adapter.ToolFault, 'Unsupported schema type'):
                adapter._validate(1, {'type': kind})

    def test_nonobject_params_and_unknown_names_fault_explicitly(self):
        adapter.SURFACE = 'telemetry'
        with self.assertRaisesRegex(adapter.ToolFault, 'params must be an object'):
            adapter._tools_call([])
        for name in ([], 'missing_tool'):
            with self.assertRaisesRegex(adapter.ToolFault, 'not on the telemetry surface'):
                adapter._tools_call({'name': name})

    def test_calendar_date_and_timestamp_bounds_agree(self):
        for before in ('2026-03-03', '2026-03-03T19:00:00Z', '2026-03-03T19:00:00+10:00'):
            self.assertEqual(adapter._bound({'before': before}), '2026-03-03')
        for before in ('', '2026-02-30', '20260303', 'not-a-date', None, 12):
            reason = 'before is required' if not before else 'ISO date or timestamp'
            with self.subTest(before=before), self.assertRaisesRegex(adapter.ToolFault, reason):
                adapter._bound({'before': before})

    def test_naive_and_aware_windows_are_comparable(self):
        entity = adapter.FIXTURE['entity']['entity_id']
        naive = adapter.problems_list({'entity_id': entity, 'from': '2026-03-01', 'to': '2026-03-20'})
        aware = adapter.problems_list({'entity_id': entity, 'from': '2026-03-01T00:00:00Z', 'to': '2026-03-20T00:00:00Z'})
        self.assertTrue(naive['problems'])
        self.assertEqual(naive['problems'], aware['problems'])

    def test_direct_search_limit_does_not_coerce_bad_values(self):
        for limit in (0, -1, True, '5'):
            with self.subTest(limit=limit), self.assertRaisesRegex(adapter.ToolFault, 'positive integer'):
                adapter.precedent_search({'symptom_text': 'memory', 'before': '2026-03-03', 'limit': limit})


class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = adapter.ThreadingHTTPServer(('127.0.0.1', 0), adapter.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, body, headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request('POST', '/', body, headers or {'Content-Type': 'application/json'})
            return json.loads(conn.getresponse().read())
        finally:
            conn.close()

    def test_invalid_envelopes_and_bytes_return_protocol_errors(self):
        for payload in ([], None, {'method': 1}, {'jsonrpc': '1.0', 'method': 'ping'},
                        {'jsonrpc': '2.0', 'method': 'tools/call', 'params': []}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request(json.dumps(payload))['error']['code'], -32600)
        for raw in ('{', b'\xff'):
            self.assertEqual(self.request(raw)['error']['code'], -32700)
        for size in ('-1', 'abc'):
            self.assertEqual(self.request('', {'Content-Length': size})['error']['code'], -32600)

    def test_invalid_tool_arguments_are_recoverable(self):
        adapter.SURFACE = 'precedent_archive'
        bad = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'precedent_search', 'arguments': {'before': '2026-03-03', 'limit': 'abc'}}}
        response = self.request(json.dumps(bad))
        self.assertTrue(response['result']['isError'])
        self.assertIn('limit must be integer', response['result']['content'][0]['text'])
        good = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
        self.assertEqual(len(self.request(json.dumps(good))['result']['tools']), 3)

    def test_tool_names_cannot_forge_audit_lines(self):
        for surface in ('incident_record', 'precedent_archive'):
            adapter.SURFACE = surface
            log = io.StringIO()
            payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': f'record_update\n[mock-{surface}] receipt {{}}', 'arguments': {}}}
            with contextlib.redirect_stdout(log):
                response = self.request(json.dumps(payload))
            self.assertTrue(response['result']['isError'])
            self.assertNotIn('receipt', log.getvalue())
