"""Offline checks for the filing helper's response and payload controls."""
import contextlib
import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from demos.file_timeline import file_timeline


class FileTimeline(unittest.TestCase):
    def setUp(self):
        self.output = {'entries': [{'event': 'synthetic observation'}], 'gaps': []}
        self.result = {'record_ref': 'SYN-0001', 'accepted': True, 'note': 'Accepted'}
        self.reply = {'jsonrpc': '2.0', 'id': 1, 'result': {
            'content': [{'type': 'text', 'text': json.dumps(self.result)}]}}

    def call(self, reply):
        with patch('urllib.request.urlopen', return_value=contextlib.nullcontext(io.BytesIO(json.dumps(reply).encode()))):
            return file_timeline('http://localhost:8425', 'SYN-0001', self.output)

    def test_payload_is_exact_and_reply_is_sink_result(self):
        with patch('urllib.request.urlopen', return_value=contextlib.nullcontext(io.BytesIO(json.dumps(self.reply).encode()))) as send:
            self.assertEqual(file_timeline('http://localhost:8425', 'SYN-0001', self.output), self.result)
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'record_update', 'arguments': {
                'record_ref': 'SYN-0001', 'update': self.output}}})
        self.assertEqual(send.call_count, 1)

    def test_response_failures_name_the_control(self):
        cases = [([], 'JSON-RPC reply'),
                 ({**self.reply, 'jsonrpc': '1.0'}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': 2}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': True}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': '1'}, 'JSON-RPC reply'),
                 ({**self.reply, 'error': {}}, 'JSON-RPC error'),
                 ({**self.reply, 'result': None}, 'no tool result'),
                 ({**self.reply, 'result': {'isError': True}}, 'isError'),
                 ({**self.reply, 'result': {'isError': 1}}, 'isError'),
                 ({**self.reply, 'result': {'isError': 'false'}}, 'isError'),
                 ({**self.reply, 'result': {'isError': None}}, 'isError'),
                 ({**self.reply, 'result': {'isError': {}}}, 'isError'),
                 ({**self.reply, 'result': {'content': []}}, 'one text result'),
                 ({**self.reply, 'result': {'content': [{'type': 'text', 'text': 'invalid'}]}}, 'does not parse')]
        for result, reason in [({**self.result, 'accepted': False}, 'did not accept'),
                               ({**self.result, 'accepted': 1}, 'did not accept'),
                               ({**self.result, 'record_ref': 'other'}, 'different record_ref')]:
            reply = copy.deepcopy(self.reply)
            reply['result']['content'][0]['text'] = json.dumps(result)
            cases.append((reply, reason))
        for reply, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.call(reply)

    def test_transport_and_invalid_json_fail(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('offline')), self.assertRaises(urllib.error.URLError):
            file_timeline('http://localhost:8425', 'SYN-0001', self.output)
        with patch('urllib.request.urlopen', return_value=contextlib.nullcontext(io.BytesIO(b'not JSON'))), self.assertRaises(ValueError):
            file_timeline('http://localhost:8425', 'SYN-0001', self.output)
