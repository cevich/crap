#!/usr/bin/env python3

import sys
import os
import tempfile
import shutil
import unittest
from glob import glob
import importlib.machinery
from pdb import Pdb


class TestCaseSubBase(unittest.TestCase):
    """Exercize code from file based on TEST_FILENAME in TESTS_DIR_PARENT + SUBJECT_REL_PATH"""

    # repo. relative path containing test subject python file
    SUBJECT_REL_PATH = 'bin'

    # Abstract attributes
    TEST_FILENAME = None
    TESTS_DIR = None
    TESTS_DIR_PARENT = None

    # When non-none, file path to module for SUBJECT
    SUBJECT_PATH = None

    # Private, do not use
    _SUBJECT = None

    # When non-none, complete path to unittest temporary directory
    TEMPDIRPATH = None

    patchers = None

    def __init__(self, methodName='runTest'):
        # The name of the loaded code, as if it were a real module
        self.SUBJECT_NAME = self.TEST_FILENAME[len('test_'):].split('.',1)[0]

        # The complete path containing SUBJECT_NAME
        self.SUBJECT_DIR = os.path.realpath(os.path.join(self.TESTS_DIR_PARENT, self.SUBJECT_REL_PATH))

        if self.patchers is None:
            self.patchers = []
        super(TestCaseSubBase, self).__init__(methodName)

    @property
    def SUBJECT(self):
        if self._SUBJECT is None:
            # The complete path to the SUBJECT_NAME
            for self.SUBJECT_PATH in glob(os.path.join(self.SUBJECT_DIR,
                                                       '{}*'.format(self.SUBJECT_NAME))):
                if os.path.isfile(self.SUBJECT_PATH):
                    # The subject may not conform to package.module standards
                    loader = importlib.machinery.SourceFileLoader(self.SUBJECT_NAME, self.SUBJECT_PATH)
                    # After python 3.6: Need loader for files w/o any extension
                    # so loader.exec_module() can be used.
                    self._SUBJECT = sys.modules[self.SUBJECT_NAME] = loader.load_module(self.SUBJECT_NAME)
                    break
            else:
                raise RuntimeError("Could not locate test subject: {} in {}"
                                   "".format(self.SUBJECT_NAME, self.SUBJECT_DIR))
        return self._SUBJECT

    def trace(self, statement=None):
        """Enter the pdb debugger, 'n' will step back to self.trace() caller"""
        return self._pdb.set_trace()

    def start_patchers(self):
        # Ensure subject is imported for patching
        _ = self.SUBJECT
        for patcher in self.patchers:
            patcher.start()

    def setUp(self):
        super(TestCaseSubBase, self).setUp()
        self._pdb = Pdb()
        self.TEMPDIRPATH = tempfile.mkdtemp(prefix=self.SUBJECT_NAME)

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        if self.TEMPDIRPATH:
            for tempdirglob in glob('{}*'.format(self.TEMPDIRPATH)):
                shutil.rmtree(tempdirglob, ignore_errors=True)
        super(TestCaseSubBase, self).tearDown()
