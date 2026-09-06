from types import SimpleNamespace

import pytest

from harness.api import sessions
from harness.api.session_control import post_chat_stash


@pytest.fixture
def stash(monkeypatch):
    monkeypatch.setattr(sessions, '_CHAT_STASH', {})
    return SimpleNamespace(stash_put=sessions.stash_put)


def test_stash_retains_document_and_delivery_identity(stash):
    body = {
        'message': '  exact original\n' * 1000,
        'images': ['input:A:image-digest'],
        'documents': [{'ref': 'input:A:document-digest', 'name': 'reference.txt'}],
        'retry_key': 'submission-key',
        'input_id': 'input-id',
        'handoff_token': 'one-use-handoff',
        'session_id': 'A',
    }
    code, response = post_chat_stash(body, stash)
    assert code == 200
    stored = sessions.stash_pop(response['id'])
    assert stored == body
    assert sessions.stash_pop(response['id']) is None


def test_document_only_draft_can_be_stashed(stash):
    code, response = post_chat_stash({'message': '', 'documents': [{'ref': 'input:A:digest'}]}, stash)
    assert code == 200
    assert sessions.stash_pop(response['id'])['documents'] == [{'ref': 'input:A:digest'}]


@pytest.mark.parametrize('body', [{'message': []}, {'message': 'valid', 'documents': 'bad'}])
def test_invalid_stash_payload_is_rejected_without_publication(stash, body):
    code, response = post_chat_stash(body, stash)
    assert code == 400
    assert response['ok'] is False
    assert sessions._CHAT_STASH == {}
