"""Deterministic subprocess crash/recall benchmark: python -m bench.compaction_durable."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

SID = 'durable_fixture'
FACTS = {'orchard': 'cobalt-finch-731', 'harbor': 'amber-wren-482', 'summit': 'violet-tern-956'}
BOUNDARIES = ('before_archive', 'after_archive', 'before_transcript_replace',
              'after_transcript_replace', 'after_success')


def isolate(state):
    os.environ['HARNESS_STATE_DIR'] = state
    os.environ['HARNESS_COMPACTION_RESIDUAL'] = 'summary'
    os.environ['HARNESS_MIN_COMPACTABLE_TOKENS'] = '0'
    os.environ['HARNESS_COMPACTION_VAULT'] = '1'

    def blocked(*args, **kwargs):
        raise AssertionError('Network disabled in deterministic compaction benchmark')
    socket.socket.connect = blocked


def use_baseline(directory):
    for name in ('compaction_archive', 'history_compaction_journal', 'sessions', 'compaction_mixin'):
        spec = importlib.util.spec_from_file_location('harness.' + name, Path(directory) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        import harness
        setattr(harness, name, module)


def session_at(state):
    from harness.config import HarnessConfig
    from harness.conversation import ConversationalSession
    session = ConversationalSession(HarnessConfig(state_dir=state, max_context_tokens=4000))
    session.harness_session_id = SID
    return session


def crash_child(state, boundary, baseline=''):
    isolate(state)
    if baseline:
        use_baseline(baseline)
    from harness import compaction_archive, sessions
    from pmharness.drivers.base import DriverResponse
    session = session_at(state)
    session._history = [{'role': 'system', 'content': 'Synthetic crash benchmark.'}]
    for i in range(10):
        session._history.extend([
            {'role': 'user', 'content': f'Fixture request {i}. ' + 'A' * 150},
            {'role': 'assistant', 'content': f'Fixture response {i}. ' + 'B' * 150},
        ])
    for position, (topic, value) in zip((5, 7, 9), FACTS.items()):
        call_id = 'fixture_' + topic
        session._history[position - 1] = {
            'role': 'assistant', 'content': '',
            'tool_calls': [{'id': call_id, 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': '{}'}}],
        }
        session._history[position] = {
            'role': 'tool', 'tool_call_id': call_id,
            'content': f'The {topic} routing label is {value}.' if topic != 'summit' else 'Pending fixture output.',
        }
    sessions.save_transcript(state, SID, session.export_transcript_data())
    # This revision has not reached the normal end-of-turn persist callback.
    session._history[9]['content'] = f'The summit routing label is {FACTS["summit"]}.'

    class SummaryPilot:
        model = 'deterministic-summary'

        def chat(self, messages, *, system):
            return DriverResponse(text=('The fixture discussed routine implementation work and follow-up verification. '
                                        'The outstanding task is to complete the next local check. ' * 3))
    session.pilot = SummaryPilot()
    append = compaction_archive.append_compaction_archive

    def archive(*args, **kwargs):
        if boundary == 'before_archive':
            os._exit(71)
        result = append(*args, **kwargs)
        if boundary == 'after_archive':
            os._exit(71)
        return result
    compaction_archive.append_compaction_archive = archive
    replace = os.replace

    def replace_at_boundary(src, dst):
        target = str(dst).endswith('/' + SID + '.json')
        if target and boundary == 'before_transcript_replace':
            os._exit(71)
        replace(src, dst)
        if target and boundary == 'after_transcript_replace':
            os._exit(71)
    os.replace = replace_at_boundary
    events = list(session._maybe_compact_history(force=True))
    if events[-1].data.get('aborted'):
        raise AssertionError(events[-1].data)
    os._exit(71 if boundary == 'after_success' else 72)


def inspect_child(state):
    isolate(state)
    from harness.compaction_archive import verified_archive_digest
    from harness.pilot import PilotAction
    from harness.sessions import load_transcript
    from harness.compaction_vault import retrieve_vault_result
    session = session_at(state)
    session.load_history(load_transcript(state, SID))
    summary = '\n'.join(str(m.get('content', '')) for m in session._history if m.get('_compressed_summary'))
    archive_path = Path(state) / 'transcripts' / (SID + '.archive.json')
    try:
        digest = verified_archive_digest(state, SID)
        archive_state = 'verified'
    except OSError:
        digest = ''
        archive_state = 'corrupt' if archive_path.exists() else 'unavailable'
    pages = []
    for offset in range(0, 60, 4):
        ok, status, body = session._do_peek_history(PilotAction(kind='peek_history', arguments={'offset': offset, 'limit': 4}))
        if ok:
            pages.append(body)
    results = []
    for topic, value in FACTS.items():
        matching = [page for page in pages if value in page]
        vault = retrieve_vault_result(state, SID, topic)
        results.append({
            'topic': topic, 'expected': value, 'summary_recalled': value in summary,
            'history_tool_recalled': bool(matching),
            'provenance': matching[0] if matching else '',
            'archive_lookup_recalled': bool(matching) and archive_state == 'verified' and value not in json.dumps(session._history),
            'source': 'archive' if bool(matching) and value not in json.dumps(session._history) else 'transcript',
            'vault_recalled': any(value in hit for hit in vault['hits']),
            'vault_route': vault['route'],
        })
    return {'archive_state': archive_state, 'archive_digest': digest,
            'residual_present': bool(summary), 'facts': results,
            'summary_exact': sum(r['summary_recalled'] for r in results),
            'archive_lookup_exact': sum(r['archive_lookup_recalled'] for r in results),
            'vault_exact': sum(r['vault_recalled'] for r in results),
            'history_tool_exact': sum(r['history_tool_recalled'] for r in results)}


def run_case(state, boundary, baseline=''):
    started = time.monotonic()
    cmd = [sys.executable, '-m', 'bench.compaction_durable', '--child', 'crash', '--state', str(state), '--boundary', boundary]
    if baseline:
        cmd += ['--baseline', baseline]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 71 and not (baseline and result.returncode == 72):
        raise AssertionError(result.stderr or result.stdout)
    return dict(inspect_cold(state), boundary=boundary, exit_code=result.returncode,
                boundary_reached=result.returncode == 71, elapsed_ms=round((time.monotonic() - started) * 1000, 2))


def inspect_cold(state):
    inspected = subprocess.run([sys.executable, '-m', 'bench.compaction_durable', '--child', 'inspect', '--state', str(state)],
                               capture_output=True, text=True, timeout=30, check=True)
    return json.loads(inspected.stdout)



def repeated_child(state):
    """Run actual compaction repeatedly, then inspect a separately attached session."""
    isolate(state)
    from harness.sessions import load_transcript
    from harness.compaction_archive import load_compaction_archive_page
    from harness.pilot import PilotAction
    from pmharness.drivers.base import DriverResponse
    session = session_at(state)
    session._history = [{'role': 'system', 'content': 'Repeated fixture.'}]
    class SummaryPilot:
        model = 'deterministic-summary'
        def chat(self, messages, *, system):
            return DriverResponse(text='Routine implementation work continues. ' * 8)
    session.pilot = SummaryPilot()
    expected = []
    for wave in range(15):
        for i in range(40):
            fact = f'EXACT-WAVE-{wave:02d}-ROW-{i:02d}-END'
            expected.append(fact)
            session._history.append({'role': 'user' if i % 2 == 0 else 'assistant',
                                     'content': fact + ' padding' * 24})
        events = list(session._maybe_compact_history(force=True))
        assert events[-1].kind == 'compaction' and not events[-1].data.get('aborted'), events[-1]
    # A fresh inspector process starts without this process's live history.
    result = subprocess.run([sys.executable, '-m', 'bench.compaction_durable',
                             '--child', 'repeated-inspect', '--state', state],
                            capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def repeated_inspect(state):
    isolate(state)
    from harness.sessions import load_transcript
    from harness.compaction_archive import load_compaction_archive_page
    from harness.pilot import PilotAction
    session = session_at(state)
    session.load_history(load_transcript(state, SID))
    _, total = load_compaction_archive_page(state, SID, limit=0)
    bodies = []
    for offset in range(0, total + len(session._history), 20):
        ok, status, body = session._do_peek_history(PilotAction(
            kind='peek_history', arguments={'offset': offset, 'limit': 20}))
        assert ok, status
        bodies.append(body)
    text = '\n'.join(bodies)
    expected = [f'EXACT-WAVE-{wave:02d}-ROW-{i:02d}-END' for wave in range(15) for i in range(40)]
    return {'archive_rows': total, 'expected_facts': len(expected),
            'exact_facts': sum(fact in text for fact in expected),
            'oldest_exact': expected[0] in text,
            'newest_exact': expected[-1] in text,
            'max_peek_bytes': max(len(body.encode()) for body in bodies)}


def normal_save_benchmark():
    """Compare the original atomic replacement with the durable write primitive.

    Both treatments serialize identical data to isolated temporary state. FTS
    is excluded to measure fsync/readback overhead rather than index variability.
    """
    import statistics
    from harness.compaction_archive import _atomic_write_json
    def previous(path, data):
        with open(path + '.tmp', 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
        os.replace(path + '.tmp', path)
    results = []
    with tempfile.TemporaryDirectory(prefix='compaction-save-cost-') as root:
        for count in (40, 400):
            data = {'history': [{'role': 'user', 'content': 'synthetic ' * 100} for _ in range(count)]}
            samples = {'atomic_replace': [], 'fsync_readback': []}
            for i in range(25):
                for name, writer in (('atomic_replace', previous), ('fsync_readback', _atomic_write_json)):
                    start = time.perf_counter()
                    writer(str(Path(root) / (name + '.json')), data)
                    elapsed = (time.perf_counter() - start) * 1000
                    if i >= 5:
                        samples[name].append(elapsed)
            medians = {name: round(statistics.median(values), 3) for name, values in samples.items()}
            results.append(dict(rows=count, serialized_bytes=len(json.dumps(data, indent=2).encode()),
                                samples=20, median_ms=medians,
                                overhead_ms=round(medians['fsync_readback'] - medians['atomic_replace'], 3)))
    return {'normal_save_io': results, 'scope': 'Local temporary filesystem, write primitive only; no FTS or concurrency.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=('crash', 'inspect', 'repeated', 'repeated-inspect', 'save-benchmark'))
    parser.add_argument('--state')
    parser.add_argument('--boundary', choices=BOUNDARIES, default='after_success')
    parser.add_argument('--baseline', default='')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.child == 'save-benchmark':
        print(json.dumps(normal_save_benchmark()))
    elif args.child == 'repeated':
        print(json.dumps(repeated_child(args.state)))
    elif args.child == 'repeated-inspect':
        print(json.dumps(repeated_inspect(args.state)))
    elif args.child == 'crash':
        crash_child(args.state, args.boundary, args.baseline)
    elif args.child == 'inspect':
        print(json.dumps(inspect_child(args.state)))
    else:
        with tempfile.TemporaryDirectory(prefix='compaction-crash-') as root:
            cases = [run_case(Path(root) / boundary, boundary, args.baseline) for boundary in BOUNDARIES]
            failures = []
            if not args.baseline:
                for damage in ('corrupt', 'unavailable'):
                    state = Path(root) / damage
                    run_case(state, 'after_success')
                    archive = state / 'transcripts' / (SID + '.archive.json')
                    if damage == 'corrupt':
                        archive.write_text('{invalid')
                    else:
                        archive.unlink()
                    failures.append(dict(inspect_cold(state), damage=damage))
        report = {'cases': cases, 'archive_failures': failures, 'all_exact': all(c['history_tool_exact'] == len(FACTS) for c in cases),
                  'scope': 'Process exits on local filesystem; not a power-loss or cross-process writer proof.'}
        output = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).write_text(output + '\n')
        else:
            print(output)


if __name__ == '__main__':
    main()
