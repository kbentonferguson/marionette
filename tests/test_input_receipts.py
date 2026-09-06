import hashlib
import json

import pytest

from harness.input_receipts import InputReceiptStore, InputReceiptError


def test_originals_retry_and_corruption(tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    image = uploads / 'one.png'
    image.write_bytes(b'original pixels')
    store = InputReceiptStore(str(tmp_path), 'session')
    first = store.admit('  exact text\n', images=[str(image)], upload_root=str(uploads), retry_key='one')
    assert store.admit('  exact text\n', images=[str(image)], upload_root=str(uploads), retry_key='one')['id'] == first['id']
    assert store.admit('  exact text\n', images=[str(image)], upload_root=str(uploads))['id'] != first['id']
    with pytest.raises(InputReceiptError):
        store.admit('different', retry_key='one')
    image.unlink()
    assert store.attachment(first['attachments'][0]['ref']) == b'original pixels'
    assert store.list()[0]['original_text'] == '  exact text\n'
    store.path.write_text('{broken')
    with pytest.raises(InputReceiptError):
        store.admit('must not overwrite')
    assert store.path.read_text() == '{broken'


def test_attempt_survives_cold_read_without_replay(tmp_path):
    store = InputReceiptStore(str(tmp_path), 'session')
    receipt = store.admit('hello')
    store.transition(receipt['id'], 'delivering')
    cold = InputReceiptStore(str(tmp_path), 'session')
    assert cold.list()[0]['status'] == 'uncertain'
    with pytest.raises(InputReceiptError):
        store.transition(receipt['id'], 'injected')


def test_attachment_validation(tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    outside = tmp_path / 'secret.png'
    outside.write_bytes(b'private')
    store = InputReceiptStore(str(tmp_path), 'session')
    with pytest.raises(InputReceiptError):
        store.admit('no', images=[str(outside)], upload_root=str(uploads))
    assert store.list() == []
