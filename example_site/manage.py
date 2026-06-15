#!/usr/bin/env python
"""Django management entrypoint for the parody book-host."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "booksite.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
