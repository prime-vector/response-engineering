#!/usr/bin/env python3
"""Receive agent traces locally as the exporter's metadata, one span per line."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer


def reexec_under_oa():
    # The otel extra lives beside oa, often in pipx, rather than in system
    # Python. Compare paths, not realpaths: a venv selects its own packages.
    oa = shutil.which("oa")
    if not oa:
        sys.exit("Cannot locate oa; install open-agent-spec[contracts,otel].")
    with open(oa) as handle:
        interpreter = handle.readline()[2:].strip().split()[0]
    if not os.path.isfile(interpreter):
        sys.exit("Cannot resolve oa's interpreter from its shebang.")
    if interpreter != sys.executable:
        os.environ["OA_AGENT_TRACES_REEXEC"] = "1"
        raise SystemExit(subprocess.call([interpreter, *sys.argv]))


if __name__ == "__main__" and not os.environ.get("OA_AGENT_TRACES_REEXEC"):
    reexec_under_oa()

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (  # noqa: E402
    ExportTraceServiceRequest, ExportTraceServiceResponse,
)
from google.protobuf.message import DecodeError  # noqa: E402


def plain(value):
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [plain(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {v.key: plain(v.value) for v in value.kvlist_value.values}
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind) if kind else None


def spans(request):
    for resource in request.resource_spans:
        for scope in resource.scope_spans:
            for span in scope.spans:
                yield {
                    "trace_id": span.trace_id.hex(),
                    "span_id": span.span_id.hex(),
                    "parent_span_id": span.parent_span_id.hex(),
                    "name": span.name,
                    "status_code": span.status.code,
                    "start_time_unix_nano": span.start_time_unix_nano,
                    "end_time_unix_nano": span.end_time_unix_nano,
                    "attributes": {a.key: plain(a.value) for a in span.attributes},
                }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/traces":
            self.reply(404)
            return
        try:
            length = int(self.headers["Content-Length"])
            if length < 0:
                raise ValueError("negative content length")
            body = self.rfile.read(length)
            encoding = self.headers.get("Content-Encoding", "identity").lower()
            if encoding == "gzip":
                body = gzip.decompress(body)
            elif encoding != "identity":
                self.reply(415)
                return
            request = ExportTraceServiceRequest.FromString(body)
        except (ValueError, TypeError, OSError, EOFError, zlib.error, DecodeError):
            self.reply(400)
            return
        # Persist only what the exporter supplied. No model or adapter content
        # is fetched or inferred here. Closing the file flushes before the ACK.
        try:
            with self.server.output.open("a", encoding="utf-8") as handle:
                for span in spans(request):
                    handle.write(json.dumps(span, ensure_ascii=False) + "\n")
        except OSError:
            self.reply(500)
            return
        self.reply(200, ExportTraceServiceResponse().SerializeToString())

    def unsupported(self):
        self.reply(405 if self.path == "/v1/traces" else 404)

    do_GET = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = unsupported

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.unsupported
        raise AttributeError(name)


def self_test():
    import io
    import tempfile
    import threading
    import urllib.error
    import urllib.request
    from types import SimpleNamespace

    request = ExportTraceServiceRequest()
    span = request.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex("01" * 16)
    span.span_id = bytes.fromhex("02" * 8)
    span.parent_span_id = bytes.fromhex("03" * 8)
    span.name = "execute_tool record_update"
    span.status.code = 1
    span.start_time_unix_nano, span.end_time_unix_nano = 10, 20
    for key, kind, value in [("string", "string_value", "metadata"),
                             ("bool", "bool_value", True),
                             ("int", "int_value", 7), ("double", "double_value", 1.5),
                             ("bytes", "bytes_value", b"\x01")]:
        a = span.attributes.add(key=key)
        setattr(a.value, kind, value)
    span.attributes.add(key="array").value.array_value.values.add().int_value = 2
    kv = span.attributes.add(key="map").value.kvlist_value.values.add(key="nested")
    kv.value.string_value = "value"
    span.attributes.add(key="unset")
    expected = {"trace_id": "01" * 16, "span_id": "02" * 8,
                "parent_span_id": "03" * 8, "name": span.name, "status_code": 1,
                "start_time_unix_nano": 10, "end_time_unix_nano": 20,
                "attributes": {"string": "metadata", "bool": True, "int": 7,
                               "double": 1.5, "bytes": "01", "array": [2],
                               "map": {"nested": "value"}, "unset": None}}
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "spans.jsonl"
        try:
            server = HTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError:
            server = None
            print("Loopback binding refused; testing the request handler directly.")
        if server:
            server.output = output
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

        def post(method, path, body, encoding="identity"):
            if server:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}{path}", data=body,
                    method=method, headers={"Content-Encoding": encoding})
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        return response.status, response.read()
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read()
            class Connection:
                def makefile(self, *_args):
                    return io.BytesIO(raw)
                def sendall(self, data):
                    reply.write(data)
            raw = (f"{method} {path} HTTP/1.0\r\nContent-Length: {len(body)}\r\n"
                   f"Content-Encoding: {encoding}\r\n\r\n").encode() + body
            reply = io.BytesIO()
            Handler(Connection(), ("127.0.0.1", 0), SimpleNamespace(output=output))
            headers, data = reply.getvalue().split(b"\r\n\r\n", 1)
            return int(headers.split()[1]), data

        try:
            encoded = request.SerializeToString()
            for body, encoding in [(encoded, "identity"), (gzip.compress(encoded), "gzip")]:
                status, response = post("POST", "/v1/traces", body, encoding)
                assert status == 200 and response == b"", (status, response)
            assert [json.loads(line) for line in output.read_text().splitlines()] == [expected] * 2
            for method, path, body, encoding, expected_status in [
                ("POST", "/other", b"", "identity", 404),
                ("GET", "/v1/traces", b"", "identity", 405),
                ("PUT", "/other", b"", "identity", 404),
                ("CUSTOM", "/v1/traces", b"", "identity", 405),
                ("POST", "/v1/traces", b"bad", "gzip", 400),
                ("POST", "/v1/traces", b"\xff", "identity", 400),
                ("POST", "/v1/traces", b"", "unknown", 415),
            ]:
                assert post(method, path, body, encoding)[0] == expected_status
            assert len(output.read_text().splitlines()) == 2
        finally:
            if server:
                server.shutdown()
                thread.join()
                server.server_close()
    print("Agent traces sink self-test passed: protobuf, gzip, value forms and HTTP errors.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.output is None:
        parser.error("output JSONL path is required")
    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.output = args.output
        args.output.touch()
        if args.ready_file:
            args.ready_file.write_text(str(server.server_port), encoding="ascii")
        server.serve_forever()


if __name__ == "__main__":
    main()
