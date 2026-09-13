import os
from sys import argv

import updater
from text_editor import edit_file


def _read_version():
    version_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "VERSION"
    )
    try:
        with open(version_path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "unknown"


if __name__ == "__main__":
    match len(argv):
        case 1:
            updater.check_for_updates_on_open()
            edit_file()

        case 2 if argv[1] == "--update":
            updater.run_update_command()

        case 2 if argv[1] == "--version":
            print(f"mini {_read_version()}")

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
