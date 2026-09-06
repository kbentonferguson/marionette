"""Owned HTTP lifecycle for in-process harness integration tests."""
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

_READY_TIMEOUT = 5.0
_JOIN_TIMEOUT = 5.0


class TestThreadingHTTPServer(ThreadingHTTPServer):
    """Track daemon handlers explicitly so teardown can join them with a bound."""

    __test__ = False
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._request_threads = []
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        # Register before start, so even a not-yet-scheduled handler is owned.
        thread = threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
            name="test-harness-http-handler",
            daemon=True,
        )
        self._request_threads = [t for t in self._request_threads if t.is_alive()]
        self._request_threads.append(thread)
        thread.start()

    def server_close(self):
        super().server_close()
        deadline = time.monotonic() + _JOIN_TIMEOUT
        for thread in self._request_threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        alive = [t.name for t in self._request_threads if t.is_alive()]
        if alive:
            raise RuntimeError(f"HTTP test handlers did not stop: {alive}")


def wait_server_ready(port, token):
    """Exercise the real Handler without running config/model discovery."""
    deadline = time.monotonic() + _READY_TIMEOUT
    last_err = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/config",
                headers={"X-Harness-Token": token},
                method="OPTIONS",
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 204:
                    resp.read()
                    return
        except Exception as exc:
            last_err = exc
            time.sleep(0.05)
    raise RuntimeError(
        f"harness test server not ready on 127.0.0.1:{port}: {last_err!r}"
    )


@contextmanager
def harness_http_server(srv, *, thread_name):
    """Capture Handler now; finish requests before caller restores shared state."""
    httpd = TestThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    thread = threading.Thread(
        target=httpd.serve_forever, name=thread_name, daemon=True,
    )
    thread.start()
    try:
        wait_server_ready(httpd.server_address[1], srv._TOKEN)
        yield srv, httpd.server_address[1]
    finally:
        try:
            httpd.shutdown()
        finally:
            try:
                httpd.server_close()
            finally:
                thread.join(timeout=_JOIN_TIMEOUT)
                if thread.is_alive():
                    raise RuntimeError(f"HTTP test serve thread did not stop: {thread.name}")
