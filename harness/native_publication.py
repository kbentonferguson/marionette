from __future__ import annotations

"""Cross-process serialization for native transcript/archive/input publication."""

from contextlib import contextmanager
import os
import threading

_LOCAL = threading.local()


@contextmanager
def native_publication(state_root):
    # Existing publication lock is first everywhere. Per-thread recursion is
    # necessary because recovery and strict writes reenter from input/archive.
    from .history_compaction_journal import _COMPACTION_COMMIT_LOCK
    root = os.path.normcase(os.path.realpath(state_root))
    with _COMPACTION_COMMIT_LOCK:
        held = getattr(_LOCAL, 'held', None)
        if held is None:
            held = _LOCAL.held = set()
        if root in held:
            yield
            return
        parent = os.path.join(root, 'transcripts')
        os.makedirs(parent, exist_ok=True)
        with open(os.path.join(parent, '.native-publication.lock'), 'a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held.add(root)
            try:
                yield
            finally:
                held.remove(root)
