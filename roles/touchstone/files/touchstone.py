#!/usr/bin/env python3

import errno
import sys
import os
import argparse
import fcntl
from contextlib import contextmanager

@contextmanager
def flock(filepath):
    if os.path.basename(filepath).startswith('.'):
        pfx_fmt = '{0}.lock'
    else:
        pfx_fmt = '.{0}.lock'
    filepath = os.path.join(os.path.dirname(filepath),
                            pfx_fmt.format(os.path.basename(filepath)))
    with open(filepath, 'a') as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            yield lockfile
        finally:
            fcntl.flock(lockfile, fcntl.LOCK_UN)


def touch_touchstone(filepath, lines):
    contents = '\n'.join(lines)
    with flock(filepath):
        try:
            with open(filepath, 'rU') as touchstone:
                contents = touchstone.read()
        except IOError as xcept:
            if xcept.errno != errno.ENOENT:
                raise
        with open(filepath, 'w') as touchstone:
            touchstone.write(contents)
            if not contents.endswith('\n'):
                touchstone.write('\n')


def is_touched(filepath):
    with flock(filepath):
        try:
            open(filepath, 'rU')
            return True
        except IOError:
            return False


def parse_arguments(argv):
    adhf = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(formatter_class=adhf,
                                     epilog='Prints "True"/"False" to stdout,'
                                            ' indicating touchstone status')
    parser.add_argument("filepath", default=None,
                       help="Path to the touchstone file to examine or update.")
    parser.add_argument('-t', '--touch', default=False, action='store_true',
                       help="Ensure the touchstone <filepath> exists, on creation"
                            " populate it with <lines>")
    parser.add_argument('lines', default=None, nargs="*",
                       help="Lines to store in <filepath> on creation.")
    try:
        return parser.parse_args(argv[1:])
    except IndexError:
        return parser.parse_args(argv)


def main(argv):
    args = parse_arguments(argv)
    if args.touch:
        touch_touchstone(args.filepath, args.lines)
    sys.stdout.write('{0}\n'.format(is_touched(args.filepath)))


if __name__ == "__main__":
    main(sys.argv)
