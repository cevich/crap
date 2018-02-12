#!/usr/bin/env python3


import sys
import os
import json
from io import StringIO
import argparse
import unittest
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from unittest.mock import MagicMock, patch, create_autospec
from unittestlib import TestCaseSubBase
import shutil
import tempfile


class TestCaseBase(TestCaseSubBase):
    # Assumes directory structure as-is from repo. clone
    TEST_FILENAME = os.path.basename(os.path.realpath(sys.modules[__name__].__file__))
    TESTS_DIR = os.path.dirname(os.path.realpath(sys.modules[__name__].__file__))
    TESTS_DIR_PARENT = os.path.realpath(os.path.join(TESTS_DIR, '../'))


    def __init__(self, methodName='runTest'):
        super(TestCaseBase, self).__init__(methodName)

        class MockFlock(object):
            acquire_read = MagicMock()
            acquire_write = MagicMock()
            timeout_acquire_read = MagicMock()
            timeout_acquire_write = MagicMock()

        # Must be done here, in setUp is too late (self.SUBJECT already loaded)
        self.mock_flock = MagicMock()
        self.mock_flock.Flock = MockFlock
        sys.modules['flock'] = self.mock_flock


class TestFuncs(TestCaseBase):
    """Tests for all the top-level functions except main"""

    fake_stdout = None
    fake_stderr = None
    exit_code = None
    exit_msg = None

    def mock_exit(self, code=None, msg=None):
        self.exit_code = code
        self.exit_msg = msg

    def setUp(self):
        super(TestFuncs, self).setUp()
        self.fake_stdout = StringIO()
        self.fake_stderr = StringIO()
        self.exit_msg = None
        self.exit_code = None
        self.patchers.append(patch('{}.ArgumentParser.exit'.format(self.SUBJECT_NAME),
                             MagicMock(side_effect=self.mock_exit)))
        self.patchers.append(patch('{}.tempfile.mkdtemp'.format(self.SUBJECT_NAME),
                             MagicMock(return_value=self.TEMPDIRPATH)))
        self.start_patchers()
        # Required for testing debugging option
        self.SUBJECT.DebugAction.disable_debugging()

    def test_noargs(self):
        """Script w/o args gives usage info"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            self.SUBJECT.parse_args(argv=[self.SUBJECT_PATH], environ={})
        self.assertEqual(self.fake_stdout.getvalue().strip(), "")
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'usage:')

    def test_debug_arg(self):
        """Script with --debug enables debug mode"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            self.SUBJECT.parse_args(argv=[self.SUBJECT_PATH, '--debug'], environ={})
        self.assertEqual(self.fake_stdout.getvalue().strip(), "")
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'Debugging enabled')

    def test_debug_env(self):
        """Script with $DEBUG enables debug mode"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            self.SUBJECT.parse_args(argv=[self.SUBJECT_PATH],
                                    environ=dict(DEBUG='some non-empty value'))
        # No exceptions, output is empty JSON dict.
        self.assertEqual(self.fake_stdout.getvalue().strip(), "")
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'Debugging enabled')

    def test_mm_help(self):
        """Script with --help gives extended usage message"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            self.SUBJECT.parse_args(argv=[self.SUBJECT_PATH, '--help'], environ={})
        self.assertEqual(self.exit_code, 2)
        for expected in ('usage:', 'positional arguments:', 'optional arguments:'):
            self.assertRegex(self.fake_stdout.getvalue().lower(), expected.lower())

    def test_no_env_defaults(self):
        """Default options have expected values"""
        dargs = dict(command='foo', args=[], debug=False)
        for key in ('artifacts', 'inituri', 'initcmd', 'timeout'):
            dargs[key] = self.SUBJECT.OPT_ARG_DEFAULTS[key]
        dargs['piles'] = None
        dargs['prog'] = '{0}.py'.format(self.SUBJECT_NAME)
        dargs['workspace'] = self.TEMPDIRPATH
        expected = argparse.Namespace(**dargs)
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            actual = self.SUBJECT.parse_args([self.SUBJECT_PATH, 'foo'], environ={})
            self.assertDictEqual(vars(expected), vars(actual))
            self.assertEqual(self.fake_stdout.getvalue(), '')
            self.assertEqual(self.fake_stderr.getvalue(), '')



class TestContext(TestCaseBase):

    @contextmanager
    def reader(self): yield self.jsonfiles[0]

    @contextmanager
    def writer(self): yield self.jsonfiles[1]

    jsonfiles = []  # Reference list so contents can be set in-line AFTER patching

    def setUp(self):
        super(TestContext, self).setUp()
        self.options = argparse.Namespace(workspace=os.path.join(self.TEMPDIRPATH, 'test_workspace'),
                                          artifacts=os.path.join(self.TEMPDIRPATH, 'test_artifacts'),
                                          prog=self.SUBJECT_NAME,
                                          inituri='foo://bar',
                                          initcmd='/usr/local/$WORKSPACE',
                                          debug=False,
                                          timeout=1,
                                          piles=42,
                                          command='/usr/local/$ARTIFACTS',
                                          args=['$PATH','${MISSING:-found}'])
        self.environ = dict(EDITOR="/usr/bin/vim", HISTSIZE="1000",
                            HOME="/land/down/under", HOSTNAME="www.microsoft.com",
                            LOGNAME="somebody",
                            PATH="/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin",
                            PWD="/tmp", SHELL="/bin/bash", SHLVL="2",
                            TERM="dumb", USER="somebody", USERNAME="somebody")
        del self.jsonfiles[:]
        self.jsonfiles.append(StringIO())
        self.jsonfiles.append(StringIO())
        self.patchers.append(patch('{}.Context.reader'.format(self.SUBJECT_NAME),
                             self.reader))
        self.patchers.append(patch('{}.Context.writer'.format(self.SUBJECT_NAME),
                             self.writer))
        self.start_patchers()

    def tearDown(self):
        shutil.rmtree(os.path.join(self.TEMPDIRPATH, 'test_workspace'), True)
        shutil.rmtree(os.path.join(self.TEMPDIRPATH, 'test_artifacts'), True)
        super(TestContext, self).tearDown()

    def test_init(self):
        """Verify initialization affect"""
        self.assertFalse(os.path.exists(self.options.workspace))
        self.assertFalse(os.path.exists(self.options.artifacts))
        original_option_dict = vars(self.options)
        context = self.SUBJECT.Context(self.options, self.environ)
        self.assertTrue(os.path.exists(self.options.workspace))
        self.assertTrue(os.path.exists(self.options.artifacts))
        self.assertTrue(os.path.exists(context.logfiledir))
        self.assertDictEqual(original_option_dict, vars(context.options))

    def test_git_clone_args(self):
        """Verify proper parsing of git repo URI + query-string"""
        qse = r'.*git clone --its working --aflag --this also .*foo/bar/baz.git'
        key = self.SUBJECT.Context.URI_QS_KEY
        default = self.SUBJECT.DEFAULT_INITURI
        for inituri, expected in {self.options.inituri: None,
                                  'file:///foo/bar/baz.git?{0}=--its&{0}=working&{0}=--aflag&{0}=--this&{0}=also'.format(key): qse,
                                  'http://foo/bar/baz.git?not=used;{0}=--its;{0}=working;{0}=--aflag;{0}=--this;{0}=also'.format(key): None,
                                  '/foo/bar/baz.git?{0}=--its;{0}=working;{0}=--aflag;{0}=--this;{0}=also'.format(key): qse,
                                  default: 'git.*clone.*{0}'.format(default)}.items():
            with self.subTest(inituri=inituri, expected=expected):
                options = argparse.Namespace(**vars(self.options))
                options.inituri = inituri
                context = self.SUBJECT.Context(options, self.environ)
                if expected is None:
                    self.assertEqual(context.git_clone_args, None)
                else:
                    self.assertRegex(' '.join(context.git_clone_args), expected)
                sys.stderr.write('.')

    def test_wget_args(self):
        context = self.SUBJECT.Context(self.options, self.environ)
        self.assertEqual(context.wget_args, None)  # "foo" isn't a valid protocol
        options = vars(self.options)
        options['inituri'] = 'https://foo/bar/?{0}=--long&{0}=option&not=this&or=this'.format(self.SUBJECT.Context.URI_QS_KEY)
        context = self.SUBJECT.Context(argparse.Namespace(**options), self.environ)
        actual = context.wget_args
        expected = ['/usr/bin/wget'] + list(context.WGET_ARGS) + ['--long', 'option',
                                                                  'https://foo/bar/?not=this;or=this']
        self.assertEqual(actual, expected)

    def test_rsync_args(self):
        bad_proto_uri = self.options.inituri  # "foo" isn't a valid protocol

        leftover_qs_uri = 'user@somewhere::/foo/bar/?{0}=--long&{0}=option&not=this&or=this'.format(self.SUBJECT.Context.URI_QS_KEY)

        good_uri = 'user@somewhere::/foo/bar/?{0}=--long;{0}=option'.format(self.SUBJECT.Context.URI_QS_KEY)
        good_expected = ['/usr/bin/rsync'] + list(self.SUBJECT.Context.RSYNC_ARGS) + [
                        '--long', 'option', 'user@somewhere::/foo/bar/']
        good_ev = 'user@somewhere::/${{var:-def}}/bar/?{0}=--long;{0}=option'.format(self.SUBJECT.Context.URI_QS_KEY)
        good_ev_expected = ['/usr/bin/rsync'] + list(self.SUBJECT.Context.RSYNC_ARGS) + [
                            '--long', 'option', 'user@somewhere::/${var:-def}/bar/']
        for uri, expected in {bad_proto_uri:None, leftover_qs_uri:None,
                              good_uri:good_expected, good_ev:good_ev_expected}.items():
            options = vars(self.options)
            options['inituri'] = uri
            with self.subTest(uri=uri, expected=expected):
                context = self.SUBJECT.Context(argparse.Namespace(**options), self.environ)
                actual = context.rsync_args
                self.assertEqual(actual, expected)
            sys.stderr.write('.')


    def test_options_workspace(self):
        """Verify options.workspace is required"""
        opts_dict = vars(self.options)
        del opts_dict['workspace']
        self.assertRaisesRegex(AttributeError, 'workspace',
                               self.SUBJECT.Context, argparse.Namespace(**opts_dict), {})


if __name__ == '__main__':
    unittest.main()
