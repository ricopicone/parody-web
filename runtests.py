#!/usr/bin/env python
"""Run the parody_web test suite standalone: `python runtests.py`."""
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")


def main():
    django.setup()
    runner = get_runner(settings)()
    sys.exit(bool(runner.run_tests(["parody_web"])))


if __name__ == "__main__":
    main()
