"""HTTP fixture regressions, runnable even where loopback bind is prohibited."""
import importlib
import io
import threading
from http.client import HTTPResponse

import pytest


_MODULES = (
    "test_self_dev_restart",
    "test_upload",
    "test_workspace_boot_restore",
)


class _Connection:
    def __init__(self, incoming=b""):
        self.incoming = incoming
        self.output = bytearray()

    def makefile(self, *args, **kwargs):
        return io.BytesIO(self.incoming)

    def sendall(self, data):
        self.output.extend(data)

    def shutdown(self, *args):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("module_name", _MODULES)
def test_readiness_does_not_run_model_discovery(monkeypatch, module_name):
    import harness.server as srv
    from harness import model_visibility

    module = importlib.import_module(module_name)
    discoveries = []
    captured_handler = srv.Handler

    def discovery():
        discoveries.append(True)
        return []

    def in_process_urlopen(req, timeout):
        wire = (
            f"{req.get_method()} {req.selector} HTTP/1.0\r\n"
            "Host: 127.0.0.1\r\n"
            f"X-Harness-Token: {srv._TOKEN}\r\n\r\n"
        ).encode()
        conn = _Connection(wire)
        # Run the actual captured Handler, auth guard and dispatch table.
        captured_handler(conn, ("127.0.0.1", 12345), object())
        response = HTTPResponse(_Connection(bytes(conn.output)))
        response.begin()
        return response

    monkeypatch.setattr(model_visibility, "enabled_pilots", discovery)
    monkeypatch.setattr(module.urllib.request, "urlopen", in_process_urlopen)
    module._wait_server_ready(12345, srv._TOKEN)
    assert not discoveries, "readiness executed model discovery"


@pytest.mark.parametrize("module_name", _MODULES)
def test_server_close_waits_for_captured_handler(module_name):
    module = importlib.import_module(module_name)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    closed = threading.Event()

    def captured_handler(request, client_address, server):
        entered.set()
        try:
            assert release.wait(10), "test did not release request handler"
        finally:
            finished.set()

    # Skip only bind/listen: process_request and server_close are real stdlib
    # lifecycle paths on both Windows and POSIX.
    server = module._TestThreadingHTTPServer(
        ("127.0.0.1", 0), captured_handler, bind_and_activate=False,
    )
    closer = None
    try:
        server.process_request(_Connection(), ("127.0.0.1", 12345))
        assert entered.wait(2)

        def close():
            server.server_close()
            closed.set()

        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        assert not closed.wait(0.2), "teardown returned with the handler still running"
        release.set()
        assert closed.wait(2)
        assert finished.is_set()
    finally:
        release.set()
        if closer is not None:
            closer.join(2)
        server.server_close()
        assert finished.wait(2)


def test_stalled_handler_teardown_has_a_deadline(monkeypatch):
    import http_server_support as support

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_handler(request, client_address, server):
        entered.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    monkeypatch.setattr(support, "_JOIN_TIMEOUT", 0.05)
    server = support.TestThreadingHTTPServer(
        ("127.0.0.1", 0), blocked_handler, bind_and_activate=False,
    )
    try:
        server.process_request(_Connection(), ("127.0.0.1", 12345))
        assert entered.wait(2)
        with pytest.raises(RuntimeError, match="HTTP test handlers did not stop"):
            server.server_close()
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(2)
        server.server_close()
