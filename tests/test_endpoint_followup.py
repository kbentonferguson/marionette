import sqlite3
import pytest
from harness.api.endpoint import get_endpoint, validate_request

@pytest.mark.parametrize('error', [sqlite3.OperationalError('private database detail'), RuntimeError('PM store failed')])
def test_factory_failure_is_structured_unavailable(error):
    def fail():
        raise error
    for status, body in (get_endpoint(fail), validate_request({'X-Harness-Protocol':'1'}, '/api/session/events', fail)):
        assert status == 503
        assert body['code'] == 'endpoint_unavailable'
        assert str(error) not in body['error']

from test_endpoint_identity import endpoint, request

@pytest.mark.parametrize('method,path', [('GET','/api/endpoint'),('GET','/api/session/events'),('POST','/api/session/persist'),('DELETE','/api/sessions/s')])
@pytest.mark.parametrize('error', [sqlite3.OperationalError('private database detail'), RuntimeError('PM store failed')])
def test_http_guard_returns_503_on_factory_failure(endpoint, monkeypatch, method, path, error):
    def fail():
        raise error
    monkeypatch.setattr(endpoint, '_endpoint_identity', fail)
    status, body = request(endpoint, path, {'X-Harness-Protocol':'1'}, method)
    assert status == 503
    assert body['code'] == 'endpoint_unavailable'
    assert str(error) not in body['error']
