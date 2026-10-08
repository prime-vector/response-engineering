"""Offline checks for the filing helper's response and payload controls."""
import contextlib
import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from demos.file_timeline import file_timeline


def reply_with(body):
    return contextlib.nullcontext(io.BytesIO(json.dumps(body).encode()))


class FileTimeline(unittest.TestCase):
    def setUp(self):
        self.output = {'entries': [{'event': 'synthetic observation'}], 'gaps': []}
        self.result = {'record_ref': 'SYN-0001', 'accepted': True, 'note': 'Accepted'}
        self.reply = {'jsonrpc': '2.0', 'id': 1, 'result': {
            'content': [{'type': 'text', 'text': json.dumps(self.result)}]}}

    def call(self, reply, output=None):
        with patch('urllib.request.urlopen', return_value=reply_with(reply)):
            return file_timeline('http://localhost:8425', 'SYN-0001', self.output if output is None else output)

    def with_result(self, **changes):
        reply = copy.deepcopy(self.reply)
        reply['result']['content'][0]['text'] = json.dumps({**self.result, **changes})
        return reply

    def test_payload_is_exact_and_reply_is_sink_result(self):
        with patch('urllib.request.urlopen', return_value=reply_with(self.reply)) as send:
            self.assertEqual(file_timeline('http://localhost:8425', 'SYN-0001', self.output), self.result)
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'record_update', 'arguments': {
                'record_ref': 'SYN-0001', 'update': self.output}}})
        self.assertEqual(send.call_count, 1)

    def test_only_the_contracted_fields_are_filed(self):
        # The contract names entries and gaps; anything else on the reply is
        # not part of the record and must not reach the sink.
        with patch('urllib.request.urlopen', return_value=reply_with(self.reply)) as send:
            file_timeline('http://localhost:8425', 'SYN-0001', {**self.output, 'extra': 'dropped'})
        sent = json.loads(send.call_args.args[0].data)['params']['arguments']['update']
        self.assertEqual(sent, self.output)

    def test_explicit_is_error_false_is_accepted(self):
        reply = copy.deepcopy(self.reply)
        reply['result']['isError'] = False
        self.assertEqual(self.call(reply), self.result)

    def test_invalid_timeline_is_refused_before_any_request(self):
        cases = [(None, 'JSON object'), ([], 'JSON object'), ('text', 'JSON object'),
                 ({'gaps': []}, 'entries must be present and a list'),
                 ({'entries': []}, 'gaps must be present and a list'),
                 ({'entries': {}, 'gaps': []}, 'entries must be present and a list'),
                 ({'entries': [], 'gaps': 'none'}, 'gaps must be present and a list'),
                 ({'entries': None, 'gaps': []}, 'entries must be present and a list')]
        for output, reason in cases:
            with self.subTest(output=output), patch('urllib.request.urlopen') as send:
                with self.assertRaisesRegex(ValueError, reason):
                    file_timeline('http://localhost:8425', 'SYN-0001', output)
                send.assert_not_called()

    def test_response_failures_name_the_control(self):
        cases = [([], 'JSON-RPC reply'),
                 ({**self.reply, 'jsonrpc': '1.0'}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': 2}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': True}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': '1'}, 'JSON-RPC reply'),
                 ({**self.reply, 'id': 1.0}, 'JSON-RPC reply'),
                 ({**self.reply, 'error': {}}, 'JSON-RPC error'),
                 ({**self.reply, 'result': None}, 'no tool result'),
                 ({**self.reply, 'result': []}, 'no tool result'),
                 ({**self.reply, 'result': {'isError': True}}, 'isError'),
                 ({**self.reply, 'result': {'isError': 1}}, 'isError'),
                 ({**self.reply, 'result': {'isError': 0}}, 'isError'),
                 ({**self.reply, 'result': {'isError': 'false'}}, 'isError'),
                 ({**self.reply, 'result': {'isError': None}}, 'isError'),
                 ({**self.reply, 'result': {'isError': {}}}, 'isError'),
                 ({**self.reply, 'result': {'content': []}}, 'one text result'),
                 ({**self.reply, 'result': {'content': None}}, 'one text result'),
                 ({**self.reply, 'result': {'content': 'text'}}, 'one text result'),
                 ({**self.reply, 'result': {'content': ['text']}}, 'one text result'),
                 ({**self.reply, 'result': {'content': [{'type': 'image', 'text': '{}'}]}}, 'one text result'),
                 ({**self.reply, 'result': {'content': [{'type': 'text'}]}}, 'does not parse'),
                 ({**self.reply, 'result': {'content': [{'type': 'text', 'text': None}]}}, 'does not parse'),
                 ({**self.reply, 'result': {'content': [{'type': 'text', 'text': 'invalid'}]}}, 'does not parse'),
                 ({**self.reply, 'result': {'content': [{'type': 'text', 'text': '[]'}]}}, 'did not accept'),
                 ({**self.reply, 'result': {'content': self.reply['result']['content'] * 2}}, 'one text result'),
                 (self.with_result(accepted=False), 'did not accept'),
                 (self.with_result(accepted=1), 'did not accept'),
                 (self.with_result(accepted='true'), 'did not accept'),
                 (self.with_result(record_ref='other'), 'different record_ref'),
                 (self.with_result(record_ref=None), 'different record_ref')]
        del_accepted = copy.deepcopy(self.reply)
        del_accepted['result']['content'][0]['text'] = json.dumps({'record_ref': 'SYN-0001'})
        cases.append((del_accepted, 'did not accept'))
        for reply, reason in cases:
            with self.subTest(reason=reason, reply=reply), self.assertRaisesRegex(ValueError, reason):
                self.call(reply)

    def test_transport_and_invalid_json_fail(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('offline')), self.assertRaises(urllib.error.URLError):
            file_timeline('http://localhost:8425', 'SYN-0001', self.output)
        with patch('urllib.request.urlopen', return_value=contextlib.nullcontext(io.BytesIO(b'not JSON'))), self.assertRaises(ValueError):
            file_timeline('http://localhost:8425', 'SYN-0001', self.output)
