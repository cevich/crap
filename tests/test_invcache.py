#!/usr/bin/env python3

import sys
import os
import tempfile
import fcntl
import json
import shutil
import subprocess
from errno import ESRCH
from io import StringIO, SEEK_SET
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import unittest
from unittest.mock import MagicMock, patch, mock_open, call, create_autospec, ANY
from glob import glob
import importlib.machinery
from pdb import Pdb

# Assumes directory structure as-is from repo. clone
TEST_FILENAME = os.path.basename(os.path.realpath(__file__))
TESTS_DIR = os.path.dirname(os.path.realpath(__file__))
TESTS_DIR_PARENT = os.path.realpath(os.path.join(TESTS_DIR, '../'))


class TestCaseBase(unittest.TestCase):
    """Exercize code from file based on TEST_FILENAME in TESTS_DIR_PARENT + SUBJECT_REL_PATH"""

    # Mock'd call for opening files, used for patching
    MockOpen = mock_open()

    # When non-None, the file-like object returned by mock_open()
    cachefile = None

    # When non-None, a stand-in for fcntl module
    mock_fcntl = None

    # repo. relative path containing test subject python file
    SUBJECT_REL_PATH = 'bin'

    # The name of the loaded code, as if it were a real module
    SUBJECT_NAME = TEST_FILENAME[len('test_'):].split('.',1)[0]

    # The complete path containing SUBJECT_NAME
    SUBJECT_DIR = os.path.realpath(os.path.join(TESTS_DIR_PARENT, SUBJECT_REL_PATH))

    # When non-none, reference to loaded subject as if it were a module
    SUBJECT = None

    # When non-none, complete path to unittest temporary directory
    TEMPDIRPATH = None

    # Fake proccess ID of parent process
    PPID = 43

    # When non-None, contains a tuple of patcher instances
    patchers = None

    # The complete path to the SUBJECT_NAME
    for SUBJECT_PATH in glob(os.path.join(SUBJECT_DIR, '{}*'.format(SUBJECT_NAME))):
        if os.path.isfile(SUBJECT_PATH):
            # The subject may not conform to package.module standards
            loader = importlib.machinery.SourceFileLoader(SUBJECT_NAME, SUBJECT_PATH)
            # After python 3.6: Need loader for files w/o any extension
            # so loader.exec_module() can be used.
            SUBJECT = sys.modules[SUBJECT_NAME] = loader.load_module(SUBJECT_NAME)
            break
    else:
        raise RuntimeError("Could not locate test subject: {} in {}".format(SUBJECT_NAME, SUBJECT_DIR))

    def trace(self, statement=None):
        """Enter the pdb debugger, 'n' will step back to self.trace() caller"""
        return self._pdb.set_trace()

    def reset(self):
        self.MockOpen.reset_mock()
        self.MockOpen.return_value = self.cachefile = StringIO()
        self.cachefile.close = MagicMock()
        self.mock_fcntl.reset_mock()
        for attr in dir(fcntl):
            mockattr = MagicMock(spec=getattr(fcntl, attr), spec_set=True)
            # represent int constants properly
            if attr.capitalize() == attr:
                mockattr.__int__ = getattr(fcntl, attr)
            self.mock_fcntl.attach_mock(mockattr, attr)
        self.SUBJECT.InvCache.reset()


    def setUp(self):
        super(TestCaseBase, self).setUp()
        self._pdb = Pdb()
        self.TEMPDIRPATH = tempfile.mkdtemp(prefix=os.path.basename(__file__))
        self.mock_fcntl = create_autospec(spec=fcntl, spec_set=True, instance=True)
        self.mock_makedirs = create_autospec(spec=os.makedirs, spec_set=True,
                                               return_value=self.TEMPDIRPATH)
        # TODO: All of ``os`` and ``sys`` should probably just be patched up inside a loop
        self.patchers = [patch('{}.tempfile.gettempdir'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=self.TEMPDIRPATH)),
                         patch('{}.tempfile.TemporaryFile'.format(TestCaseBase.SUBJECT_NAME),
                               create_autospec(spec=tempfile.TemporaryFile)),
                         patch('{}.tempfile.mkdtemp'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=self.TEMPDIRPATH)),
                         patch('{}.os.makedirs'.format(TestCaseBase.SUBJECT_NAME),
                               self.mock_makedirs),
                         patch('{}.os.path.isdir'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(spec=os.path.isdir, return_value=False)),
                         patch('{}.os.getcwd'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=self.TEMPDIRPATH)),
                         patch('{}.fcntl'.format(TestCaseBase.SUBJECT_NAME),
                               self.mock_fcntl),
                         patch('{}.open'.format(format(TestCaseBase.SUBJECT_NAME)),
                               self.MockOpen, create=True),
                         patch('{}.InvCache.filename'.format(TestCaseBase.SUBJECT_NAME),
                               property(fget=MagicMock(return_value='bar'))),
                         patch('{}.os.chdir'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(spec=self.SUBJECT.os.chdir)),
                         patch('{}.os.setsid'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(spec=self.SUBJECT.os.setsid)),
                         patch('{}.os.umask'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(spec=self.SUBJECT.os.umask)),
                         patch('{}.os.closerange'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(spec=self.SUBJECT.os.closerange)),
                         patch('{}.os.fork'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=0)),
                         patch('{}.os.getpid'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=42)),
                         patch('{}.os.getppid'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=self.PPID)),
                         patch('{}.os.getgid'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=44)),
                         patch('{}.os.unlink'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=45)),
                         patch('{}.os.chmod'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=46)),
                         patch('{}.os.getuid'.format(TestCaseBase.SUBJECT_NAME),
                               MagicMock(return_value=47))]
        for patcher in self.patchers:
            patcher.start()
        self.reset()

    def tearDown(self):
        if hasattr(self, 'patchers'):
            for patcher in self.patchers:
                patcher.stop()
        if self.TEMPDIRPATH:  # rm -rf /tmp/test_invcache.py*
            for tempdirglob in glob('{}*'.format(self.TEMPDIRPATH)):
                shutil.rmtree(tempdirglob, ignore_errors=True)

    def validate_mock_fcntl(self):
        """Helper to confirm cachefile-locking/unlocking was done properly"""
        # Make sure unlock happens _after_ locking, and lock is released
        locked = False
        locks = 0
        unlocks = 0
        for args, dargs in self.mock_fcntl.flock.call_args_list:
            if locked:
                if len(args) >= 2:
                    op = args[1]
                elif 'op' in dargs:
                    op = dargs['op']
                else:
                    continue  # Don't care about this call
                # Is it a locking call?
                if op == self.mock_fcntl.LOCK_UN:
                    locked = False
                    unlocks += 1
            else:
                if len(args) >= 2:
                    op = args[1]
                elif 'op' in dargs:
                    op = dargs['op']
                else:
                    continue  # Don't care about this call
                if op in [self.mock_fcntl.LOCK_EX, self.mock_fcntl.LOCK_SH]:
                    locked = True
                    locks += 1
        self.assertFalse(locked, "Mock cache file locked {} times but"
                                 " unlocked {} times".format(locks, unlocks))


class TestToolFunctions(TestCaseBase):
    """Tests for several misc. tooling functions"""

    def validate_artifacts_dirpath(self, environ, expect, raises=None,
                                   art_ro=False, tmp_art_ro=False, tmp_ro=False,
                                   ws_art_ro=False, ws_ro=False):
        """Helper for actual tests"""

        if expect:
            expect = expect.format(TMP=self.TEMPDIRPATH)

        def failif_tmp_art(name, mode=511, exist_ok=False):
            self.assertEqual(mode, 511)
            self.assertEqual(exist_ok, False)  # Python2 doesn't have exist_ok option
            if tmp_art_ro and os.path.join(self.TEMPDIRPATH, 'artifacts') == name:
                raise OSError('{TMP}/artifacts is read-only'.format(TMP=self.TEMPDIRPATH))
            if tmp_ro and self.TEMPDIRPATH == name:
                raise OSError('{TMP} is read-only'.format(TMP=self.TEMPDIRPATH))
            if ws_art_ro and '/workspace/artifacts' == name:
                raise OSError('/workspace/artifacts is read-only')
            if ws_ro and '/workspace' == name:
                raise OSError('/workspace is read-only')
            if art_ro and '/artifacts' == name:
                raise OSError('/artifacts is read-only')

        self.mock_makedirs.side_effect=failif_tmp_art
        if raises:
            self.assertRaises(raises, self.SUBJECT.artifacts_dirpath, environ)
            return
        actual = self.SUBJECT.artifacts_dirpath(environ)
        self.assertEqual(actual, expect)
        self.mock_makedirs.assert_any_call(name=expect)


    def test_artifacts_dirpath(self):
        """Verify artifacts_dirpath() returns expoected paths."""
        env_ws = dict(WORKSPACE='/workspace')
        env_art = dict(ARTIFACTS='/artifacts')
        env_all = dict(WORKSPACE='/workspace', ARTIFACTS='/artifacts')
        inputs_expected = (
            dict(environ={}, expect='{TMP}/artifacts'),
            dict(environ={}, tmp_ro=True, expect='{TMP}/artifacts'),
            dict(environ={}, ws_ro=True, expect='{TMP}/artifacts'),
            dict(environ={}, ws_art_ro=True, expect='{TMP}/artifacts'),
            dict(environ={}, tmp_art_ro=True, expect='{TMP}'),
            dict(environ={}, tmp_art_ro=True, ws_ro=True, expect='{TMP}'),
            dict(environ={}, tmp_art_ro=True, ws_art_ro=True, expect='{TMP}'),
            dict(environ={}, tmp_art_ro=True, tmp_ro=True, raises=OSError, expect=None),

            dict(environ=env_ws, expect='/workspace/artifacts'),
            dict(environ=env_ws, ws_ro=True, expect='/workspace/artifacts'),
            dict(environ=env_ws, ws_art_ro=True, expect='/workspace'),
            dict(environ=env_ws, ws_ro=True, ws_art_ro=True, expect='{TMP}/artifacts'),
            dict(environ=env_ws, ws_ro=True, ws_art_ro=True, tmp_art_ro=True, expect='{TMP}'),

            dict(environ=env_art, expect='/artifacts'),
            dict(environ=env_art, ws_ro=True, expect='/artifacts'),
            dict(environ=env_art, ws_art_ro=True, expect='/artifacts'),
            dict(environ=env_art, art_ro=True, expect='{TMP}/artifacts'),
            dict(environ=env_art, art_ro=True, ws_ro=True, expect='{TMP}/artifacts'),
            dict(environ=env_art, art_ro=True, ws_art_ro=True, expect='{TMP}/artifacts'),

            dict(environ=env_all, expect='/artifacts'),
            dict(environ=env_all, art_ro=True, expect='/workspace/artifacts'),
            dict(environ=env_all, art_ro=True, ws_art_ro=True, expect='/workspace'),
            dict(environ=env_all, art_ro=True, ws_art_ro=True, ws_ro=True, expect='{TMP}/artifacts'),
            dict(environ=env_all, art_ro=True, ws_art_ro=True, ws_ro=True, tmp_art_ro=True, expect='{TMP}'),
            dict(environ=env_all, art_ro=True, ws_art_ro=True, ws_ro=True, tmp_art_ro=True, tmp_ro=True, raises=OSError, expect=None),
        )
        for input_expect in inputs_expected:
            with self.subTest(str(input_expect), input_expect=input_expect):
                self.validate_artifacts_dirpath(**input_expect)
                sys.stderr.write('.')
            self.reset()
        sys.stderr.write('\n')


class TestInvCache(TestCaseBase):
    """Tests for the InvCache class"""

    def test_init_newcache(self):
        """Verify InvCache initialization behavior"""
        invcache = self.SUBJECT.InvCache()
        self.MockOpen.assert_called_with(os.path.join(self.TEMPDIRPATH, 'bar'), 'a+')
        self.assertDictEqual(invcache.DEFAULT_CACHE, json.loads(self.cachefile.getvalue()))
        self.validate_mock_fcntl()

    def test_reset(self):
        """Verify resetting results in new instance"""
        invcache = self.SUBJECT.InvCache()
        self.validate_mock_fcntl()
        invcache.reset()
        invcache_too = self.SUBJECT.InvCache()
        self.validate_mock_fcntl()
        self.assertTrue(id(invcache) != id(invcache_too))

    def test_empty_gethost(self):
        """Verify invcache.gethost() returns None when not found"""
        invcache = self.SUBJECT.InvCache()
        self.assertEqual(invcache.gethost('foobar'), None)
        self.assertEqual(invcache.gethost(None), None)
        self.validate_mock_fcntl()

    def _inin(self, lhs, rhs):
        for key in lhs[1]:
            self.assertIn(key, rhs[1])

    def test_addgetdelhost(self):
        """Verify invcache.gethost() == invcache.addhost() == invcache.delhost()"""
        invcache = self.SUBJECT.InvCache()
        filepath = invcache.filepath
        added = invcache.addhost('foobar')
        geted = invcache.gethost('foobar')
        deled = invcache.delhost('foobar')
        self.validate_mock_fcntl()
        self.assertTrue(added)
        self.assertTrue(geted)
        self.assertTrue(deled[1])
        self._inin(geted, deled)
        self._inin(geted, deled)
        self.assertEqual(geted[0], {})
        self.assertIn('all', geted[1])
        self.assertIn('subjects', geted[1])
        #self.SUBJECT.os.unlink.assert_called_once_with(os.path.join(self.TEMPDIRPATH, 'bar'))
        self.SUBJECT.os.unlink.assert_called_once_with(filepath)
        self.assertDictEqual(invcache.DEFAULT_CACHE, json.loads(self.cachefile.getvalue()))

    def test_updategetdelhost(self):
        """Verify invcache.gethost() == invcache.updatehost() == invcache.delhost()"""
        invcache = self.SUBJECT.InvCache()
        added = invcache.updatehost('foobar')
        geted = invcache.gethost('foobar')
        deled = invcache.delhost('foobar')
        self.validate_mock_fcntl()
        self.assertTrue(added)
        self.assertTrue(geted)
        self.assertTrue(deled)
        self._inin(added, geted)
        self._inin(geted, deled)

    def test_updategethost(self):
        """Verify invcache.gethost() == invcache.updatehost() == invcache.delhost()"""
        invcache = self.SUBJECT.InvCache()
        invcache.updatehost('foobar', hostvars=dict(baz=True))
        hostvars, groups = invcache.gethost('foobar')
        for defgrp in invcache.DEFAULT_GROUPS:
            self.assertIn(defgrp, groups)
        self.assertDictEqual(hostvars, dict(baz=True))

        _hostvars, _groups = invcache.updatehost('foobar', hostvars=dict(baz=True, answer=42))
        self.assertDictEqual(_hostvars, dict(baz=True, answer=42))
        for group in _groups:
            self.assertIn(group, groups)

        invcache.updatehost('foobar', hostvars=dict(baz=False))
        _hostvars, _groups = invcache.gethost('foobar')
        self.assertDictEqual(_hostvars, dict(baz=False, answer=42))
        self.assertEqual(_groups, groups)

        self.validate_mock_fcntl()


class TestMain(TestCaseBase):
    """Tests for the ``main()`` function"""

    fake_stdout = None
    fake_stderr = None
    exit_code = None
    exit_msg = None

    def mock_exit(self, code, msg):
        self.exit_code = code
        self.exit_msg = msg

    def reset(self):
        super(TestMain, self).reset()
        self.fake_stdout = StringIO()
        self.fake_stderr = StringIO()
        self.exit_code = None
        self.exit_msg = None

    def setUp(self):
        self.fake_stdout = StringIO()
        self.fake_stderr = StringIO()
        super(TestMain, self).setUp()
        _patch = patch('{}.argparse.ArgumentParser.exit'.format(TestCaseBase.SUBJECT_NAME),
                       MagicMock(side_effect=self.mock_exit))
        self.patchers.append(_patch)
        _patch.start()

    def test_noargs(self):
        """Script w/o args returns nothing"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            try:
                self.SUBJECT.main(argv=[self.SUBJECT_PATH], environ={})
            except RuntimeError:
                if self.exit_code:
                    pass
                else:
                    raise
        # No exceptions, output is empty JSON dict.
        self.assertEqual(self.fake_stdout.getvalue().strip(), "{}")
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'usage:')

    def test_debug_arg(self):
        """Script with --debug enables debug mode"""
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            self.SUBJECT.main(argv=[self.SUBJECT_PATH, '--debug'], environ={})
        # No exceptions, output is empty JSON dict.
        self.assertEqual(self.fake_stdout.getvalue().strip(), "{}")
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'Debugging enabled')

    def test_bad_mmhost(self):
        """--host w/o any hostname exits non-zero."""
        argv = [self.SUBJECT_PATH, '--host']
        environ = {}
        with redirect_stdout(self.fake_stdout), redirect_stderr(self.fake_stderr):
            try:
                self.SUBJECT.main(argv, environ)
            except TypeError as xcept:
                pass  # No clue why argparse throws this only while under test
        self.assertFalse(self.fake_stdout.getvalue())
        self.assertTrue(self.exit_code)
        self.assertRegex(self.fake_stderr.getvalue(), r'usage:')

if __name__ == '__main__':
    unittest.main()
