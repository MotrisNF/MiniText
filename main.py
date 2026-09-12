import os
from sys import argv

from text_editor import edit_file


if __name__ == "__main__":
    match len(argv):
        case 1:
            edit_file()

        case 2:
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
