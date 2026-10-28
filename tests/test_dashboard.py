import io
import json
from dataclasses import asdict
from types import SimpleNamespace

from bbdevbox.dashboard import handler_class
from bbdevbox.dataset import Task


class Request:
    def __init__(self, path, headers=""):
        self.incoming = io.BytesIO(f"GET {path} HTTP/1.0\r\n{headers}\r\n".encode())
        self.outgoing = bytearray()

    def makefile(self, *args):
        return self.incoming

    def sendall(self, data):
        self.outgoing.extend(data)


def fetch(store, path, headers=""):
    socket = Request(path, headers)
    handler_class(store)(socket, ("127.0.0.1", 1234), SimpleNamespace())
    head, body = bytes(socket.outgoing).split(b"\r\n\r\n", 1)
    return head.decode(), body


def test_dashboard_snapshots_comparison_and_sse_replay(store, config):
    key = store.new_run(config.as_dict(), "dataset", [asdict(Task("task", "do work", "true"))], {}, [])
    row = store.attempts(key)[0]
    store.event(key, row["id"], "first", status="running", step=1)
    first_seq = store.events(key)[0]["seq"]
    store.event(key, row["id"], "second", status="passed", step=2)
    store.finish_run(key, "completed")
    head, body = fetch(store, "/")
    assert "200 OK" in head and b"Agent Observatory" in body
    assert "frame-ancestors 'none'" in head
    assert json.loads(fetch(store, "/api/info")[1])["root"] == str(store.root)
    js_head, js = fetch(store, "/dashboard.js")
    assert "text/javascript" in js_head and b"function selectRun" in js
    assert json.loads(fetch(store, "/api/runs")[1])[0]["passed_tasks"] == 1
    assert json.loads(fetch(store, "/api/run/" + key)[1])["attempts"][0]["step"] == 2
    assert json.loads(fetch(store, "/api/compare?ids=" + key)[1])["common_completed_attempts"] == 1
    head, body = fetch(store, "/api/events?run=" + key, f"Last-Event-ID: {first_seq}\r\n")
    assert "text/event-stream" in head
    assert b'"kind": "second"' in body and b'"kind": "first"' not in body
    assert b"event: done" in body
    assert "400" in fetch(store, "/api/run/invalid")[0]
