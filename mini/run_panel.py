"""Running the current file (`:run`), linting it (`:lint`), or any
bash command (`:cmd`): all three share one live pty-backed output
panel with Ctrl+C, scrolling, and Esc-to-close."""

import os
import pty
import re
import shlex
import signal
import subprocess
import sys

import terminal
import venv_detect

RUN_OUTPUT_LINE_LIMIT = 10000


def _reset_child_signals():
    # Mini ignores SIGINT/SIGQUIT for itself so Ctrl+C can't kill the
    # editor; that disposition is otherwise inherited across fork+exec,
    # which would make a :run child ignore them too. Reset both to the
    # default before exec so the child (and our SIGINT forwarding) work
    # normally.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGQUIT, signal.SIG_DFL)


_RUN_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _sanitize_run_output(text):
    def keep_only_colors(match):
        return match.group() if match.group().endswith("m") else ""

    text = _RUN_ANSI_PATTERN.sub(keep_only_colors, text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


class RunPanelMixin:

    def _resolve_python_executable(self):
        """Which python3 :run/:lint should use: an already-activated
        virtualenv wins outright; otherwise Mini looks for one of its
        own (.venv/venv/env/.env) starting at the file's own directory
        and walking up to the worktree root; failing that, Mini's own
        interpreter."""
        python_path = venv_detect._active_venv_python()
        if python_path:
            return python_path
        start_directory = (
            os.path.dirname(os.path.abspath(self.file_name))
            if self.file_name else self.worktree_root
        )
        python_path = venv_detect._find_project_venv_python(
            start_directory, self.worktree_root
        )
        return python_path or sys.executable

    def _environment_for(self, python_path):
        """Env for a :run/:lint subprocess: puts `python_path`'s own
        bin/ directory first on PATH, so a project virtualenv's own
        flake8/mypy (found by name inside :lint's shell command) are
        picked up ahead of whatever's on the system PATH."""
        env = dict(os.environ)
        bin_directory = os.path.dirname(python_path)
        env["PATH"] = bin_directory + os.pathsep + env.get("PATH", "")
        return env

    def _lint_environment(self, python_path):
        """Env for :lint specifically: the same PATH as
        `_environment_for`, with Mini's own bundled flake8/mypy
        (installed alongside jedi - see install.sh) appended as a
        last-resort fallback. A project's own flake8/mypy, if it has
        them anywhere on its PATH, are always found first - Mini's
        copies only ever get reached when a project has neither.
        Never used for :run or :cmd - only :lint should ever fall
        back to a tool that isn't actually the project's own."""
        env = self._environment_for(python_path)
        mini_bin_directory = os.path.dirname(sys.executable)
        env["PATH"] = env["PATH"] + os.pathsep + mini_bin_directory
        return env

    def _start_process(self, command, label, env=None, cwd=None,
                       save_first=True):
        """Runs `command` in a pty, streaming its output live into the
        same panel `:run`/`:terminal` uses - shared by `:lint` and
        `:cmd` too, so all three get live output, Ctrl+C, scrolling,
        and Esc-to-close for free. `env`, when given, replaces the
        child's environment (used to put a virtualenv's own bin/
        directory first on PATH). `cwd`, when given, overrides the
        default of running next to the current file. `save_first`
        skips the current-file save (and the prompt for a name if it
        has none) for `:cmd`, which need not be about this file at
        all."""
        if self.run_process is not None and self.run_process.poll() is None:
            self.run_focused = True
            self.status = "A run is already in progress"
            return
        if save_first and (self.modified or self.file_name is None):
            if not self._save():
                return
        try:
            master_fd, slave_fd = pty.openpty()
        except OSError as error:
            self.status = f"Could not run: {error}"
            return
        try:
            process = subprocess.Popen(
                command,
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                cwd=cwd if cwd is not None else (
                    os.path.dirname(self.file_name) or "."
                ),
                close_fds=True,
                preexec_fn=_reset_child_signals,
                env=env,
            )
        except OSError as error:
            os.close(master_fd)
            os.close(slave_fd)
            self.status = f"Could not run: {error}"
            return
        os.close(slave_fd)
        self.run_process = process
        self.run_master_fd = master_fd
        self.run_output_lines = [f"$ {label}"]
        self.run_pending_text = ""
        self.run_focused = True
        self.run_view_start = None
        terminal.set_run_output_fd(master_fd)

    def _require_python_file(self, action_label):
        """`_start_run`/`_start_lint`'s shared guard - both only ever
        make sense for a .py file, and differ only in which word goes
        into the status message when there isn't one. Returns the
        resolved interpreter path, or None (after setting
        self.status) if there's nothing to run/lint."""
        if not self._is_python_file():
            self.status = f"Can only {action_label} .py files"
            return None
        return self._resolve_python_executable()

    def _start_run(self):
        python_path = self._require_python_file("run")
        if python_path is None:
            return
        self._start_process(
            [python_path, os.path.basename(self.file_name)],
            f"{python_path} {self.file_name}",
            env=self._environment_for(python_path),
        )

    def _start_lint(self):
        python_path = self._require_python_file("lint")
        if python_path is None:
            return
        name = shlex.quote(os.path.basename(self.file_name))
        # --python-executable makes mypy resolve imports/stubs against
        # the project's own interpreter regardless of *which* mypy
        # binary actually ends up running - its own (found first) or
        # Mini's bundled fallback (see _lint_environment) - so falling
        # back to Mini's copy still checks the file against what the
        # project actually has installed, instead of spamming
        # "cannot find module" for every third-party import Mini's
        # own virtualenv doesn't happen to have. flake8 needs no such
        # flag - it's pure AST-based static analysis, never dependent
        # on what's actually importable.
        quoted_python_path = shlex.quote(python_path)
        shell_command = (
            f"flake8 {name}; "
            f"mypy --python-executable {quoted_python_path} {name}; "
            "rm -rf .mypy_cache"
        )
        self._start_process(
            ["sh", "-c", shell_command], "lint",
            env=self._lint_environment(python_path),
        )

    def _start_cmd(self, shell_text):
        """`:cmd <text>` - runs `text` as a bash command in the same
        output panel as :run/:lint, for anything that isn't about
        running the current file itself (installing a dependency,
        listing a directory, activating a venv for that one command,
        ...). Unlike :run/:lint, it never forces a save of the current
        buffer - :cmd need not have anything to do with it - and runs
        next to the file being edited if there is one, or at the
        worktree root otherwise."""
        if not shell_text:
            self.status = "Usage: :cmd <shell command>"
            return
        cwd = (
            os.path.dirname(os.path.abspath(self.file_name))
            if self.file_name else self.worktree_root
        )
        python_path = self._resolve_python_executable()
        self._start_process(
            ["bash", "-c", shell_text], shell_text,
            env=self._environment_for(python_path),
            cwd=cwd, save_first=False,
        )

    def _pump_run_output(self):
        try:
            data = os.read(self.run_master_fd, 4096)
        except OSError:
            data = b""
        if not data:
            self._finish_run()
            return
        text = self.run_pending_text + _sanitize_run_output(
            data.decode("utf-8", errors="replace")
        )
        *complete_lines, self.run_pending_text = text.split("\n")
        self.run_output_lines.extend(complete_lines)
        overflow = len(self.run_output_lines) - RUN_OUTPUT_LINE_LIMIT
        if overflow > 0:
            self.run_output_lines = self.run_output_lines[overflow:]
            # Lines are being dropped from the front, so a scrolled-up
            # (non-pinned) view has to shift back by the same amount
            # to keep pointing at the same content instead of quietly
            # drifting to the wrong lines.
            if self.run_view_start is not None:
                self.run_view_start = max(0, self.run_view_start - overflow)

    def _finish_run(self):
        exit_code = None
        if self.run_process is not None:
            exit_code = self.run_process.poll()
            if exit_code is None:
                self.run_process.wait()
                exit_code = self.run_process.returncode
        if self.run_master_fd is not None:
            try:
                os.close(self.run_master_fd)
            except OSError:
                pass
        terminal.set_run_output_fd(None)
        self.run_process = None
        self.run_master_fd = None
        if self.run_pending_text:
            self.run_output_lines.append(self.run_pending_text)
            self.run_pending_text = ""
        self.run_output_lines.append("")
        self.run_output_lines.append(
            f"[Process finished with exit code {exit_code}]"
        )
        self.run_output_lines.append("(Press Esc to close)")

    def _scroll_run_output(self, key):
        """Moves the output panel's view. UP/DOWN by one line,
        CTRL-UP/CTRL-DOWN by a page. Scrolling up un-pins the view from
        the live tail; scrolling back down to the bottom re-pins it,
        so new output resumes auto-following (`tail -f`-style) rather
        than requiring a DOWN per line forever to catch back up."""
        run_display_lines = self.run_output_lines
        if self.run_pending_text:
            run_display_lines = run_display_lines + [self.run_pending_text]
        max_start = max(0, len(run_display_lines) - self._run_rows)
        current_start = (
            max_start if self.run_view_start is None
            else min(self.run_view_start, max_start)
        )
        step = self._run_rows if key in ("CTRL-UP", "CTRL-DOWN") else 1
        if key in ("UP", "CTRL-UP"):
            self.run_view_start = max(0, current_start - step)
        else:
            new_start = min(current_start + step, max_start)
            self.run_view_start = None if new_start >= max_start else new_start

    def _stop_run(self):
        if self.run_process is not None and self.run_process.poll() is None:
            self.run_focused = False
            return
        if self.run_process is not None:
            self._finish_run()
        self.run_output_lines = []
        self.run_pending_text = ""
        self.run_focused = False
        self.run_view_start = None
