import os
import sys
from sys import argv

import theme
import updater
from text_editor import edit_file

_CLI_HELP_LINES = (
    "NAME",
    "    mini - a small terminal text editor",
    "",
    "DESCRIPTION",
    "    Mini is a small terminal text editor written in pure Python,",
    "    with no external dependencies. It renders directly with ANSI",
    "    escape sequences in a raw-mode terminal, and includes syntax",
    "    highlighting, inline autocompletion, and a file explorer for",
    "    Python files, while staying usable as a general-purpose text",
    "    editor for anything else.",
    "",
    "USAGE",
    "    mini                 Start with an empty, unnamed buffer",
    "    mini <file>          Open a file (created on save if it",
    "                         doesn't exist)",
    "    mini <directory>     Open the worktree file explorer for a",
    "                         directory (mini . for the current one)",
    "",
    "OPTIONS",
    "    --version            Print the installed version",
    "    --update             Check for updates and install them if",
    "                         found",
    "    --config             Open ~/.minirc as a tab",
    "    --uninstall          Remove Mini and its configuration",
    "    --help               Show this help",
    "",
    "Once open, type :help inside the editor for the full in-editor",
    "command and keybinding reference.",
    "",
    "Press q to exit.",
)


def _read_version():
    version_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "VERSION"
    )
    try:
        with open(version_path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def _show_cli_help():
    from terminal import raw_terminal, read_key

    with raw_terminal():
        sys.stdout.write("\r\n".join(_CLI_HELP_LINES) + "\r\n")
        sys.stdout.flush()
        while read_key() != "q":
            pass


if __name__ == "__main__":
    match len(argv):
        case 1:
            updater.check_for_updates_on_open()
            edit_file()

        case 2 if argv[1] == "--update":
            updater.run_update_command()

        case 2 if argv[1] == "--version":
            print(f"mini {_read_version()}")

        case 2 if argv[1] == "--config":
            edit_file(theme.RC_PATH)

        case 2 if argv[1] == "--uninstall":
            updater.run_uninstall_command()

        case 2 if argv[1] == "--help":
            _show_cli_help()

        case 2 if argv[1].startswith("--"):
            print(f"'{argv[1]}' is not a valid command. Use 'mini --help'.")

        case 2:
            updater.check_for_updates_on_open()
            try:
                if os.path.isdir(argv[1]):
                    edit_file(worktree_root=argv[1])
                else:
                    edit_file(argv[1])
            except OSError as e:
                print(f"'mini' cannot open the file '{argv[1]}': {e}")

        case _:
            print(
                f"'mini' accepts at most 2 arguments.\nReceived: {len(argv)}"
            )
