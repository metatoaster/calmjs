# -*- coding: utf-8 -*-
import unittest

from types import ModuleType
from os.path import abspath
from os.path import dirname
from os.path import join
from os.path import pardir
from os.path import relpath
import sys

import calmjs
from calmjs import loader

calmjs_base_dir = abspath(join(dirname(calmjs.__file__), pardir))


class LoaderTestCase(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_register(self):
        def bar_something():
            pass

        registry = {'foo': {}, 'bar': {}}
        with self.assertRaises(TypeError):
            loader.register('foo', registry=registry)(bar_something)

        loader.register('bar', registry=registry)(bar_something)
        self.assertEqual(registry['bar']['something'], bar_something)

    def test_get_modpath_last_empty(self):
        module = ModuleType('nothing')
        self.assertEqual(loader.modpath_last(module), [])

    def test_get_modpath_last_multi(self):
        module = ModuleType('nothing')
        module.__path__ = ['/path/to/here', '/path/to/there']
        self.assertEqual(loader.modpath_last(module), ['/path/to/there'])

    def test_get_modpath_all_empty(self):
        module = ModuleType('nothing')
        self.assertEqual(loader.modpath_all(module), [])

    def test_get_modpath_all_multi(self):
        module = ModuleType('nothing')
        module.__path__ = ['/path/to/here', '/path/to/there']
        self.assertEqual(
            loader.modpath_all(module),
            ['/path/to/here', '/path/to/there'],
        )

    def test_module1_loader_es6(self):
        from calmjs.testing import module1
        results = {
            k: relpath(v, calmjs_base_dir)
            for k, v in loader.mapper_es6(module1).items()
        }
        self.assertEqual(results, {
            'calmjs/testing/module1/hello': 'calmjs/testing/module1/hello.js',
        })

    def test_module1_loader_python(self):
        from calmjs.testing import module1
        results = {
            k: relpath(v, calmjs_base_dir)
            for k, v in loader.mapper_python(module1).items()
        }
        self.assertEqual(results, {
            'calmjs.testing.module1.hello': 'calmjs/testing/module1/hello.js',
        })