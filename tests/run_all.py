#!/usr/bin/env python3
"""Runs every tests/test_*.py module's TESTS list and prints a
pass/fail summary. No pytest/external dependencies, in keeping with
Mini's own 'no external dependencies' rule - just plain functions and
assert. Not installed by install.sh; development-only.

Usage: python3 tests/run_all.py
"""

import glob
import importlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    test_files = sorted(glob.glob(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_*.py")
    ))
    passed, failed = 0, 0
    for path in test_files:
        module_name = os.path.splitext(os.path.basename(path))[0]
        module = importlib.import_module(module_name)
        for test in getattr(module, "TESTS", []):
            label = f"{module_name}.{test.__name__}"
            try:
                test()
            except AssertionError as error:
                failed += 1
                print(f"FAIL  {label}: {error}")
            except Exception:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"ERROR {label}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"ok    {label}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
