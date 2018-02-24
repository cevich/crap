#!/usr/bin/env python

"""
Pile: initializes, layers, and executes.

Pile sets up an working directory, from a local or remote location.
Optionally utilizing an initialization or update script, before
executing a primary command.  Supports parallel execution against
the same <WORKSPACE>.
"""

import sys
import atexit
import re
import os
import time
from argparse import ArgumentParser, REMAINDER, Action, Namespace, ArgumentDefaultsHelpFormatter
from contextlib import contextmanager
from socket import gethostname
import json
import errno
from pprint import pformat
import tempfile
import shutil
from shlex import split
import subprocess
try:
    from urllib.parse import urlparse, urlunparse, parse_qs
except ImportError:
    from urlparse import urlparse, urlunparse, parse_qs
# Assume flock module is next to this module
sys.path.append(os.path.dirname(__file__))
import flock

SCRIPT_DIR = os.path.dirname(os.path.abspath('{0}/../'.format(sys.argv[0])))
EPILOG = """
All commands receive current env. vars.  In addition, env. vars. cooresponding to
all long-options (in upper-case) will be set.  A $PILES value counts (from 0), the
executions against <WORKSPACE> for use in <INITCMD> or <COMMAND>.  It is your
responsibility to ensure the safety of all URI's and commands.
"""

DEFAULT_ARTIFACTS = os.path.abspath("{0}/artifacts".format(tempfile.gettempdir()))
DEFAULT_INITURI = "https://github.com/cevich/crap.git"
DEFAULT_INITCMD = '{0}/bin/crap_pile.sh'.format(SCRIPT_DIR)
DEFAULT_TIMEOUT = 300
# option names to default values mapping for convenience
OPT_ARG_DEFAULTS = dict(artifacts=DEFAULT_ARTIFACTS,
                        inituri=DEFAULT_INITURI,
                        initcmd=DEFAULT_INITCMD,
                        timeout=DEFAULT_TIMEOUT)

class DebugAction(Action):

    """Argument processor to enable global debugging upon entry."""

    # When non-none, debug messages also written here
    log_file = None

    # private, do not use.
    _log_file_buffer = None

    def __init__(self, option_strings, dest, default=False, required=False, help=None):
        expected = set(['-d', '--debug'])
        if set(option_strings) != expected:
            raise ValueError("DebugAction instance can only handle options {0}".format(expected))
        super(DebugAction, self).__init__(option_strings=option_strings, dest=dest,
              nargs=0, const=True, default=default, required=required, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        # Enable debugging before possible argument parser exit()
        if self.const:
            self.enable_debugging()
        else:
            self.disable_debugging()
        setattr(namespace, self.dest, self.const)

    @classmethod
    def enable_debugging(cls):
        before = cls.dbgmsg
        cls.dbgmsg = staticmethod(cls._debug_enabled)
        sys.tracebacklimit = 1000
        if before != cls._debug_enabled:
            DebugAction.dbgmsg("Debugging enabled: {0} (UTC)".format(time.asctime(time.gmtime())))

    @classmethod
    def disable_debugging(cls):
        sys.tracebacklimit = 0
        cls.dbgmsg = staticmethod(cls._debug_disabled)

    @classmethod
    def _log_msg(cls, raw_lines, to_file):
        out_lines = ['DEBUG: {0}'.format(line).rstrip() for line in raw_lines]
        to_file.write('\n'.join(out_lines))
        to_file.flush()

    @classmethod
    def _handle_buffer(cls, msg):
        split_msg = msg.splitlines()

        if cls.log_file and cls._log_file_buffer is not None:
            cls._log_msg(cls._log_file_buffer, cls.log_file)  # flush buffer
            cls._log_file_buffer = None  # discontinue use
        elif not cls.log_file:  # buffer message
            if cls._log_file_buffer is None:
                cls._log_file_buffer = []
            cls._log_file_buffer.extend(split_msg)
        else:  # Save message into file
            cls._log_msg(split_msg, cls.log_file)

        return split_msg

    @classmethod
    def _debug_enabled(cls, msg):
        cls._log_msg(cls._handle_buffer(msg), sys.stderr)
        return msg

    @classmethod
    def _debug_disabled(cls, msg):
        cls._handle_buffer(msg)
        return msg

    # Disabled by default
    dbgmsg = _debug_disabled


# For convenience
dbgmsg = lambda msg: getattr(DebugAction, 'dbgmsg')(msg)


class Context(flock.Flock):

    """
    Protects workspace context details with read/write locking accessors.
    """

    CTX_FILENAME_PREFIX = ".pile"
    CTX_FILENAME_SUFFIX = ".json"
    WGET_ARGS = ("--no-host-directories", "--no-verbose")
    WGET_PROTOS = ('HTTP://', 'HTTPS://', 'FTP://')
    RSYNC_ARGS = ('--recursive', '--links', '--delay-updates', '--whole-file',
                  '--safe-links', '--perms', '--times',
                  "--exclude='.venv'", "--exclude='.pile.*'", "--exclude='.cache'")
    RSYNC_SRC_REGEX = re.compile(r'^(rsync://)?([\w\.\-]+@)?([\w\.\-]+::?)?/([\w\.\-\$\{\}\:]+)')
    URI_QS_KEY = '*'

    def __init__(self, options, environ):
        self._environ = environ  # private, do not use
        self.__environ = {}  # private
        self.options = options
        self.logfileprefix = '{0}_{1}_'.format(self.options.prog,
                                               gethostname().split('.', 1)[0])
        self.logfiledir = os.path.join(self.options.artifacts, self.options.prog)
        self.def_path = self.options.workspace  # needed by base-class
        self.def_prefix = self.CTX_FILENAME_PREFIX  # this too
        self.ctx_filepath = os.path.join(self.options.workspace,
                                         '{0}{1}'.format(self.CTX_FILENAME_PREFIX,
                                                         self.CTX_FILENAME_SUFFIX))
        dbgmsg("Using context data file: {0}".format(self.ctx_filepath))
        self.mkdirs('workspace', self.options.workspace)
        self.mkdirs('artifacts', self.options.artifacts)
        self.mkdirs('logfile', self.logfiledir)
        super(Context, self).__init__()  # uses def_path / def_prefix

    @classmethod
    def parse_qs_args(cls, uri):
        """Return a tuple or uri + CSV args extracted from the query-string (if any)"""
        frags = list(urlparse(uri))
        urlquery = parse_qs(frags[4], keep_blank_values=True)
        try:
            values = urlquery.pop(cls.URI_QS_KEY)
            extra_args = [value.strip()
                          for value in values
                          if value.strip()]
        except KeyError:
            extra_args = []
        # Re-assemble any remaining query back into a string
        new_qs = []
        fmt = '{0}={1}'
        for key, value in urlquery.items():
            new_qs += [fmt.format(key, item) for item in value]
        frags[4] = ';'.join(new_qs)
        dbgmsg('Unparsed query-string fragment: {0}'.format(pformat(frags[4])))
        new_uri = urlunparse(tuple(frags))
        return (new_uri, extra_args)

    @staticmethod
    def has_qs_or_wildcard(uri):
        """Return True if uri contains query-string or wild-card characters"""
        for qs_delimeter in ('?', '&', ';', '*'):
            if uri.rfind(qs_delimeter) != -1:  # leftover qs keys - not supported
                dbgmsg('Found additional, unsupported query-string delimeter {0} in {0}'
                       ''.format(qs_delimeter, uri))
                return True
        return False

    @property
    def git_clone_args(self):
        """Returns the git clone args to be used for options.inituri or None."""
        uri = self.options.inituri
        # Critical differentiator:  '.git' always appears in repository locations
        new_uri, extra_args = self.parse_qs_args(uri)
        if new_uri.find('.git') < 0 or self.has_qs_or_wildcard(new_uri):
            dbgmsg('Not a git URI: {0}'.format(new_uri))
            return None
        dbgmsg('Additional git clone arguments parsed from query-string: {0}'
               .format(pformat(extra_args)))
        return ['/usr/bin/git', 'clone'] + extra_args + [new_uri]

    @property
    def wget_args(self):
        """Return the complete wget command, or None if unknown protocol"""
        uri = self.options.inituri
        for proto in self.WGET_PROTOS:
            if uri.startswith(proto.lower()) or uri.startswith(proto):
                break
        else:
            dbgmsg('Not a wget URI: {0}'.format(uri))
            return None
        new_uri, extra_args = self.parse_qs_args(uri)
        dbgmsg('Additional wget arguments parsed from query-string: {0}'
               .format(pformat(extra_args)))
        return ['/usr/bin/wget'] + list(self.WGET_ARGS) + extra_args + [new_uri]

    @property
    def rsync_args(self):
        """Returns the rsync command and args to be used for uri"""
        uri = self.options.inituri
        for proto in self.WGET_PROTOS:  # not supported by rsync
            if uri.startswith(proto.lower()) or uri.startswith(proto):
                return None
        new_uri, extra_args = self.parse_qs_args(uri)
        # Some minimal basic sanity checking - no support for env-vars in user/host part
        good = (not self.has_qs_or_wildcard(new_uri) and
                bool(self.RSYNC_SRC_REGEX.search(new_uri)) or os.path.exists(new_uri))
        if not good:
            dbgmsg('Not a rsync URI: {0}'.format(new_uri))
            return None
        dbgmsg('Additional rsync arguments parsed from query-string: {0}'
               .format(pformat(extra_args)))
        return ['/usr/bin/rsync'] + list(self.RSYNC_ARGS) + extra_args + [new_uri]

    @property
    def env_override(self):
        """Return only the env. vars that will be overriden for commands"""
        return dict(WORKSPACE=self.options.workspace,
                            ARTIFACTS=self.options.artifacts,
                            INITCMD=self.options.initcmd,
                            INITURI=self.options.inituri,
                            DEBUG=str(self.options.debug),
                            TIMEOUT=str(self.options.timeout),
                            PILES=str(self.options.piles))

    @property
    def environ(self):
        """Return dictionary of env. vars overridden by some option values"""
        if not self.__environ:
            self.__environ.update(self._environ)
            self.__environ.update(self.env_override)
        return self.__environ

    @staticmethod
    def mkdirs(name, path):
        """Ensure the directory for name, at path exists, ignores errors."""
        try:
            os.makedirs(path)
        except OSError as xcept:
            if xcept.errno != errno.EEXIST:
                raise
        dbgmsg("Using {0} {1}".format(name, path))

    def handle_piles(self, ctx_file, increment=False):
        """Initialize piles count in ctx_file, increment when True"""
        try:
            existing_options = Namespace(**json.load(ctx_file))
        except (TypeError, ValueError, IOError):
            existing_options = self.options
            existing_options.piles = 0
        if increment:
            existing_options.piles += 1
        self.options.piles = existing_options.piles
        ctx_file.truncate(0)
        json.dump(vars(existing_options), ctx_file, skipkeys=True, indent=2, sort_keys=True)
        ctx_file.write('\n')  # makes it pretty

    @contextmanager
    def _context_reader_writer(self, call, method, timeout_method):
        if self.options.timeout:
            with method():
                yield call()
        else:
            with timeout_method(self.options.timeout):
                yield call()

    def reader(self):
        """Protects current context from changes by another process"""
        call = lambda: open(self.ctx_filepath, 'r', 1)
        return self._context_reader_writer(call, self.acquire_read, self.timeout_acquire_read)

    def writer(self):
        """Protects other contexts from changes by this process"""
        call = lambda: open(self.ctx_filepath, 'a+', 1)
        return self._context_reader_writer(call, self.acquire_write, self.timeout_acquire_write)

    def _subprocess(self, args, cwd, stdin=False):
        shell = executable=self._environ.get('SHELL', '/bin/bash')
        cmd = ' '.join(['{0}'.format(arg.strip()) for arg in args])
        os.chdir(cwd)
        stdio_args = dict()
        if not stdin:
            stdio_args = dict(stdin=open('/dev/null', 'r+'))
        check_call_args = dict(args=[shell, '-x', '-c', cmd], executable=shell,
                                     cwd=cwd, close_fds=True, env=self.environ,
                                     bufsize=1, **stdio_args)
        dbgmsg("Executing in {0}: {1}".format(shell, cmd))
        dbgmsg("Execution env. var. overrides:\n{0}".format(pformat(self.env_override)))
        return subprocess.check_call(**check_call_args)

    def initcmd(self):
        """Execute options.initcmd w/ or w/o downloading inituri first"""
        if self.options.initcmd.strip():
            if self.options.inituri.strip():
                inittmp = tempfile.mkdtemp(suffix='tmp', prefix='initcmd_')
                os.chdir(inittmp)
                atexit.register(shutil.rmtree, path=inittmp, ignore_errors=True)
                if self.options.inituri:
                    git = self.git_clone_args
                    wget = self.wget_args
                    rsync = self.rsync_args
                    pfx = 'The inituri looks like a'
                    if git:
                        dbgmsg('{0} git repo: {1}'.format(pfx, git[-1]))
                        cmd = git + [inittmp]
                    elif wget:
                        dbgmsg('{0} wget url: {1}'.format(pfx, wget[-1]))
                        cmd = wget
                    elif rsync:
                        dbgmsg('The inituri looks like a rsync SRC')
                        dbgmsg('{0} rsync src: {1}'.format(pfx, rsync[-1]))
                        cmd = rsync + ['{0}/'.format(inittmp)]
                    else:
                        raise ValueError("The inituri does not seem to match a git, wget,"
                                         " or rsync scheme: {0}"
                                         .format(self.options.inituri))
                    self._subprocess(cmd, inittmp)
            else:
                inittmp = self.options.workspace
            self._subprocess(split(self.options.initcmd, comments=True, posix=True), inittmp)
            dbgmsg("Initialization/Update complete")
        else:
            dbgmsg("Not using Initialization/Update  command")

    def command(self):
        """Execute command+args from the workspace"""
        self._subprocess([self.options.command] + self.options.args,
                         self.options.workspace, stdin=True)
        dbgmsg("Command complete")


def parse_args(argv=sys.argv, environ=os.environ):
    prog = os.path.basename(argv[0])
    argv = argv[1:]
    if environ.get('DEBUG', 'false').strip().lower() != 'false':
        DebugAction.enable_debugging()
    parser = ArgumentParser(prog=prog, description=__doc__, epilog=EPILOG,
                            formatter_class=ArgumentDefaultsHelpFormatter)
    # So default-value can be printed in --help
    tmpws = tempfile.mkdtemp(prefix='{0}_tmp_workspace_'.format(prog))
    atexit.register(shutil.rmtree, path=tmpws, ignore_errors=True)
    parser.add_argument("-w", "--workspace", metavar="WORKSPACE",
                        default=environ.get("WORKSPACE", tmpws),
                        help="Writable directory for containing runtime state."
                              " Defaults to $WORKSPACE, or temporary"
                              " directory that will be removed on exit."
                              " For example: ")
    parser.add_argument("-a", "--artifacts", metavar="ARTIFACTS",
                        default=environ.get('ARTIFACTS', DEFAULT_ARTIFACTS),
                        help="Writable directory containing outputs intended"
                             " to persist after <WORKSPACE>.")
    parser.add_argument("-i", "--inituri", metavar="INITURI",
                        default=environ.get('INITURI', DEFAULT_INITURI),
                        help="A git, wget, or rsync compatible URI of"
                             " contents for <INITCMD> to setup/update <WORKSPACE>."
                             " Additional arguments may be specified as values"
                             " to one or more '{0}' query-string keys."
                             "  e.g. http://foo/bar.git?{0}=--branch;{0}=master"
                             "".format(Context.URI_QS_KEY))
    parser.add_argument("-c", "--initcmd", metavar="INITCMD",
                        default=environ.get('INITCMD', DEFAULT_INITCMD),
                        help="Complete command to execute in temporary directory"
                             " holding contents from <INITURI>.")
    parser.add_argument("-t", "--timeout", metavar="TIMEOUT", type=int,
                        default=int(environ.get('TIMEOUT', DEFAULT_TIMEOUT)),
                        help="Number of seconds to wait for another {0} process to finish"
                             " executing an <INITCMD> for <WORKSPACE>."
                             "".format(prog))
    parser.add_argument("-d", "--debug", action=DebugAction,
                        default=environ.get('DEBUG', 'false').lower() != 'false',
                        help="Display additional operational details on stderr.")
    # These two will consume any/all remaining options/arguments
    parser.add_argument("command", metavar="COMMAND",
                        help="Path and/or name of a command to execute in"
                             " <WORKSPACE> after ant <INITCMD> is run.  May be relative,"
                             " absolute, or resolved by $PATH.")
    parser.add_argument("args", metavar="ARGS", nargs=REMAINDER,
                        help="All remaining arguments will be passed through double-quoted"
                             " to <COMMAND> for execution using the default shell.")

    options = parser.parse_args(argv)
    options.prog = prog  # needed for reference elsewhere
    options.piles = None  # Check-value, confirmed/set by context.handle_piles()
    # Relative paths may mess with executing commands later
    options.workspace = os.path.abspath(options.workspace)
    options.artifacts = os.path.abspath(options.artifacts)
    dbgmsg("Parsed options:")
    dbgmsg(pformat(options))
    return options


def main(argv=sys.argv, environ=os.environ):

    context = Context(parse_args(argv, environ), environ)
    atexit.register(dbgmsg, "Cleaning up")

    with context.writer() as ctx_file: # Write-lock: Workspace being manipulated
        context.handle_piles(ctx_file)
        if context.options.piles:
            logfilepath = os.path.join(context.logfiledir,
                                       '{0}_{1}.log'
                                       ''.format(context.logfileprefix,
                                                 os.getpid()))
        else:
            # Indicate this was the initial run
            logfilepath = os.path.join(context.logfiledir,
                                       '{0}_0.log'.format(context.logfileprefix))
        # Flushes all prior messages
        DebugAction.log_file = open(logfilepath,'a', 0)
        context.initcmd()

    with context.reader() as ctx_file: # Read-lock: Workspace is being used
        context.command()

    with context.writer() as ctx_file: # Write-lock: Pile count increment
        context.handle_piles(ctx_file, True)


if __name__ == '__main__':
    sys.tracebacklimit = 0
    main()
