"""A jedi-backed completion used to run synchronously, in-process, on
Mini's single key-reading loop - measured at ~100-160ms per new
completion context, and over a second for the very first one of a
session, both blocking every keystroke while they ran. Covers moving
that work to a background thread (python_introspection.py's
`_start_background_jedi_completion`/`_prewarm_jedi`) and the caching
layer built on top of it in autocomplete.py."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mini",
))
import autocomplete  # noqa: E402
import python_introspection as pi  # noqa: E402


def test_background_completion_runs_off_the_calling_thread():
    """The job must actually execute on its own thread - a caller
    blocked here would defeat the entire point."""
    calling_thread = threading.current_thread()
    saw_thread = []

    original = pi._jedi_completions

    def fake_completions(*args):
        saw_thread.append(threading.current_thread())
        return {"fake_result"}

    pi._jedi_completions = fake_completions
    try:
        event, box = pi._start_background_jedi_completion(
            "code", "f.py", 1, 0, "/usr/bin/python3",
        )
        assert event.wait(1.0)
        assert box[0] == {"fake_result"}
        assert saw_thread[0] is not calling_thread
    finally:
        pi._jedi_completions = original


def test_background_completion_notifies_the_wakeup_fd():
    read_fd, write_fd = os.pipe()
    try:
        pi.set_suggestion_wakeup_fd(write_fd)
        original = pi._jedi_completions
        pi._jedi_completions = lambda *a: None
        try:
            event, _ = pi._start_background_jedi_completion(
                "code", "f.py", 1, 0, "/usr/bin/python3",
            )
            assert event.wait(1.0)
            import select
            ready, _, _ = select.select([read_fd], [], [], 1.0)
            assert ready, "wakeup fd was never written to"
        finally:
            pi._jedi_completions = original
    finally:
        pi.set_suggestion_wakeup_fd(None)
        os.close(read_fd)
        os.close(write_fd)


def test_prewarm_jedi_never_raises_even_without_jedi_installed():
    """Best-effort, exactly like every other jedi entry point here -
    must not crash the caller regardless of whether jedi (or a usable
    environment for it) is actually available."""
    pi._prewarm_jedi("/definitely/not/a/real/interpreter")
    time.sleep(0.05)  # let the background thread run to completion


class FakeSuggestionEditor(autocomplete.SuggestionMixin):
    """Just enough of TextEditor for `_jedi_attribute_completions`/
    `_module_member_names` to run against directly."""

    def __init__(self, lines):
        self.lines = lines
        self.line = 0
        self.column = len(lines[0])
        self.file_name = "f.py"
        self._suggestion_caches = autocomplete.SuggestionCaches()

    def _resolve_python_executable(self):
        return "/usr/bin/python3"


def _patch_background_completion(monkeypatch_result, delay=0.0):
    """Swaps in a fake `_start_background_jedi_completion` that
    finishes with `monkeypatch_result` after `delay` seconds - `0.0`
    resolves before the caller's own short synchronous wait even
    checks, simulating an already-warm/fast jedi; anything at or above
    it simulates one still computing."""
    def fake_start(*args):
        event = threading.Event()
        box = [None]

        def worker():
            time.sleep(delay)
            box[0] = monkeypatch_result
            event.set()

        threading.Thread(target=worker, daemon=True).start()
        return event, box

    return fake_start


def test_jedi_attribute_completions_returns_fast_result_immediately():
    fake = FakeSuggestionEditor(["thing.attr"])
    original = autocomplete._start_background_jedi_completion
    autocomplete._start_background_jedi_completion = (
        _patch_background_completion({"foo", "bar"}, delay=0.0)
    )
    try:
        result = fake._jedi_attribute_completions(5)
        assert result == {"foo", "bar"}
        cache_key = (id(fake.lines), 0, 5)
        assert fake._suggestion_caches.jedi_attribute[cache_key] == result
        assert cache_key not in fake._suggestion_caches.jedi_pending
    finally:
        autocomplete._start_background_jedi_completion = original


def test_jedi_attribute_completions_falls_back_while_still_pending():
    fake = FakeSuggestionEditor(["thing.attr"])
    original = autocomplete._start_background_jedi_completion
    autocomplete._start_background_jedi_completion = (
        _patch_background_completion({"foo"}, delay=0.5)
    )
    try:
        # Still running - must return None (heuristics take over) well
        # under the 0.5s the fake job is deliberately held up for.
        result = fake._jedi_attribute_completions(5)
        assert result is None
        cache_key = (id(fake.lines), 0, 5)
        assert cache_key not in fake._suggestion_caches.jedi_attribute
        assert cache_key in fake._suggestion_caches.jedi_pending

        time.sleep(0.6)  # let the fake job actually finish

        # A later call (the next render, in real usage) picks up the
        # real answer instead of relaunching another job.
        result = fake._jedi_attribute_completions(5)
        assert result == {"foo"}
        assert cache_key in fake._suggestion_caches.jedi_attribute
        assert cache_key not in fake._suggestion_caches.jedi_pending
    finally:
        autocomplete._start_background_jedi_completion = original


def test_jedi_attribute_completions_never_starts_a_second_job_meanwhile():
    fake = FakeSuggestionEditor(["thing.attr"])
    calls = []
    original = autocomplete._start_background_jedi_completion

    def counting_start(*args):
        calls.append(args)
        return _patch_background_completion(set(), delay=0.3)(*args)

    autocomplete._start_background_jedi_completion = counting_start
    try:
        fake._jedi_attribute_completions(5)
        fake._jedi_attribute_completions(5)
        fake._jedi_attribute_completions(5)
        assert len(calls) == 1
    finally:
        autocomplete._start_background_jedi_completion = original


def test_module_member_names_falls_back_to_subprocess_once_jedi_lands_empty():
    fake = FakeSuggestionEditor(["from os import "])
    original = autocomplete._start_background_jedi_completion
    introspected = []
    original_introspect = autocomplete._introspect_module_members
    autocomplete._introspect_module_members = (
        lambda *a: introspected.append(a) or {"path", "getcwd"}
    )
    autocomplete._start_background_jedi_completion = (
        _patch_background_completion(None, delay=0.0)
    )
    try:
        result = fake._module_member_names("os")
        assert result == {"path", "getcwd"}
        assert introspected  # subprocess fallback actually ran
    finally:
        autocomplete._start_background_jedi_completion = original
        autocomplete._introspect_module_members = original_introspect


def test_module_member_names_does_not_spawn_a_subprocess_while_pending():
    """The subprocess fallback is itself blocking - it must not fire
    on every render while jedi's background job is still running, only
    once jedi has actually finished (successfully or not)."""
    fake = FakeSuggestionEditor(["from os import "])
    original = autocomplete._start_background_jedi_completion
    introspected = []
    original_introspect = autocomplete._introspect_module_members
    autocomplete._introspect_module_members = (
        lambda *a: introspected.append(a) or set()
    )
    autocomplete._start_background_jedi_completion = (
        _patch_background_completion({"path"}, delay=0.5)
    )
    try:
        result = fake._module_member_names("os")
        assert result == set()
        assert introspected == []
    finally:
        autocomplete._start_background_jedi_completion = original
        autocomplete._introspect_module_members = original_introspect


TESTS = [
    test_background_completion_runs_off_the_calling_thread,
    test_background_completion_notifies_the_wakeup_fd,
    test_prewarm_jedi_never_raises_even_without_jedi_installed,
    test_jedi_attribute_completions_returns_fast_result_immediately,
    test_jedi_attribute_completions_falls_back_while_still_pending,
    test_jedi_attribute_completions_never_starts_a_second_job_meanwhile,
    test_module_member_names_falls_back_to_subprocess_once_jedi_lands_empty,
    test_module_member_names_does_not_spawn_a_subprocess_while_pending,
]
