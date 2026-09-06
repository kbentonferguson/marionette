"""Filesystem failure boundaries for portable plugin replacement."""
import json
from pathlib import Path

import pytest

from harness import plugin_registry as registry
from harness.agent_plugins import AgentPluginError
from tests.test_agent_plugins import _valid_package, plugins_home


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


def prepared(tmp_path):
    source = _valid_package(tmp_path / 'source')
    manifest = json.loads((source / 'plugin.json').read_text())
    manifest['extensions'] = {'marionette': {'requested_capabilities': ['fs']}}
    (source / 'plugin.json').write_text(json.dumps(manifest))
    old = registry.install_from_path(str(source))
    registry.consent_plugin_capabilities(old.id, ['fs'])
    registry.enable_plugin(old.id)
    manifest['version'] = '2.0.0'
    manifest['extensions']['marionette']['requested_capabilities'] = ['fs', 'shell']
    (source / 'plugin.json').write_text(json.dumps(manifest))
    return source, old


@pytest.mark.parametrize('failure', ['copy', 'manifest', 'stamp', 'enabled', 'consent', 'load'])
def test_failed_replacement_restores_package_and_state(plugins_home, tmp_path, monkeypatch, failure):
    source, old = prepared(tmp_path)
    before = snapshot(registry.plugins_dir())
    original_copy = registry.shutil.copytree
    original_stamp = registry.write_integrity_stamp
    original_load = registry.load_agent_plugin

    def copy(src, dst, *args, **kwargs):
        if Path(src) == source and failure == 'copy':
            Path(dst).mkdir()
            (Path(dst) / 'plugin.json').write_bytes((source / 'plugin.json').read_bytes())
            raise OSError('interrupted copy')
        result = original_copy(src, dst, *args, **kwargs)
        if Path(src) == source:
            if failure == 'manifest':
                (Path(dst) / 'plugin.json').write_text('{}')
        return result

    def stamp(path):
        result = original_stamp(path)
        if failure == 'stamp':
            registry.integrity_stamp_path(path).write_text('{}')
        return result

    def fail_write(*args, **kwargs):
        raise OSError('state write failed')

    def load(path, data):
        if failure == 'load' and Path(path) == Path(old.path):
            raise AgentPluginError('final load failed')
        return original_load(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(registry.shutil, 'copytree', copy)
        patch.setattr(registry, 'write_integrity_stamp', stamp)
        patch.setattr(registry, 'load_agent_plugin', load)
        if failure == 'enabled':
            patch.setattr(registry, '_write_enabled', fail_write)
        if failure == 'consent':
            patch.setattr(registry, '_write_capability_records', fail_write)
        with pytest.raises((OSError, AgentPluginError)):
            registry.install_from_path(str(source), force=True)
    assert snapshot(registry.plugins_dir()) == before
    assert [p.name for p in registry.plugins_dir().iterdir() if p.is_dir()] == [old.id]
    assert registry.verify_integrity_stamp(Path(old.path)) == old.sha256
    assert len(registry.list_enabled_plugin_skills()) == 1
    assert registry.discover_plugins()[0].version == '1.2.3'


def test_replacement_requires_explicit_enable_and_consent(plugins_home, tmp_path):
    source, old = prepared(tmp_path)
    new = registry.install_from_path(str(source), force=True)
    assert new.version == '2.0.0'
    assert new.path == old.path
    assert not new.enabled
    assert new.consented_capabilities == []
    assert registry.list_enabled_plugin_skills() == []
    assert len(registry.discover_plugins()) == 1
    with pytest.raises(AgentPluginError, match='consent'):
        registry.enable_plugin(new.id)
    registry.consent_plugin_capabilities(new.id, ['fs', 'shell'])
    registry.enable_plugin(new.id)
    registry.enable_plugin(new.id)
    assert len(registry.list_enabled_plugin_skills()) == 1
    servers = registry.list_enabled_mcp_servers()
    assert len(servers) == 1
    assert next(iter(servers.values()))['args'] == [str(Path(new.path) / 'server.py')]
    assert [p.name for p in registry.plugins_dir().iterdir() if p.is_dir()] == [old.id]


def test_enable_does_not_write_consent(plugins_home, tmp_path, monkeypatch):
    source = _valid_package(tmp_path / 'source')
    installed = registry.install_from_path(str(source))
    def fail(*args, **kwargs):
        raise AssertionError('enable must not publish consent records')
    monkeypatch.setattr(registry, '_write_capability_records', fail)
    assert registry.enable_plugin(installed.id).enabled


def test_discovery_waits_for_replacement(plugins_home, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    source, old = prepared(tmp_path)
    entered, release, reader_started = Event(), Event(), Event()
    original = registry._write_enabled

    def paused(enabled):
        entered.set()
        assert release.wait(5)
        original(enabled)

    def discover():
        reader_started.set()
        return registry.discover_plugins()

    monkeypatch.setattr(registry, '_write_enabled', paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(registry.install_from_path, str(source), force=True)
        try:
            assert entered.wait(5)
            reader = pool.submit(discover)
            assert reader_started.wait(5)
            assert not reader.done()
        finally:
            release.set()
        assert writer.result().version == '2.0.0'
        records = reader.result()
    assert [(r.id, r.version, r.enabled) for r in records] == [(old.id, '2.0.0', False)]


@pytest.mark.parametrize('existing', [False, True])
def test_failed_state_publication_restores_even_after_write(plugins_home, tmp_path, monkeypatch, existing):
    if existing:
        source, _ = prepared(tmp_path)
    else:
        source = _valid_package(tmp_path / 'source')
    root = registry.plugins_dir()
    before = snapshot(root)
    original = registry._write_capability_records
    def fail(records):
        original(records)
        raise OSError('failure after state publication')
    monkeypatch.setattr(registry, '_write_capability_records', fail)
    with pytest.raises(OSError):
        registry.install_from_path(str(source), force=True)
    assert snapshot(root) == before
    assert not list(root.glob('.install-*'))


def test_failed_directory_publication_restores_old(plugins_home, tmp_path, monkeypatch):
    source, old = prepared(tmp_path)
    before = snapshot(registry.plugins_dir())
    replace = registry.os.replace
    def fail(src, dst):
        if Path(src).name == 'new' and Path(dst) == Path(old.path):
            raise OSError('directory publication failed')
        return replace(src, dst)
    monkeypatch.setattr(registry.os, 'replace', fail)
    with pytest.raises(OSError, match='publication'):
        registry.install_from_path(str(source), force=True)
    assert snapshot(registry.plugins_dir()) == before
    assert not list(registry.plugins_dir().glob('.install-*'))
