# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest
from io import StringIO
import json
import os
import sys
from os.path import exists
from os.path import join
from os.path import pathsep
import pkg_resources
import warnings

from calmjs import cli
from calmjs.testing.mocks import MockProvider
from calmjs.testing.utils import fake_error
from calmjs.testing.utils import mkdtemp
from calmjs.testing.utils import remember_cwd
from calmjs.testing.utils import stub_dist_flatten_egginfo_json
from calmjs.testing.utils import stub_mod_call
from calmjs.testing.utils import stub_mod_check_output
from calmjs.testing.utils import stub_os_environ


class CliGenerateMergeDictTestCase(unittest.TestCase):

    def test_merge(self):
        result = cli.generate_merge_dict(
            ['key'], {'key': {'foo': 1}}, {'baz': 1}, {'key': {'bar': 1}})
        self.assertEqual(result, {'key': {
            'foo': 1,
            'bar': 1,
        }})

    def test_merge_multi(self):
        result = cli.generate_merge_dict(
            ['key', 'mm'],
            {'key': {'foo': 1}},
            {'mm': {'snek': 'best'}},
            {'key': {'foo': 2}})
        self.assertEqual(result, {
            'key': {'foo': 2},
            'mm': {'snek': 'best'},
        })

    def test_merge_none_matched(self):
        result = cli.generate_merge_dict(
            ['none', 'match'], {'key': 'foo'}, {'bar': 1}, {'key': 'bar'})
        self.assertEqual(result, {})

    def test_using_actual_use_case(self):
        spec1 = {
            'dependencies': {
                'jquery': '~3.0.0',
                'underscore': '~1.8.0',
            },
            'devDependencies': {
                'sinon': '~1.17.0'
            },
            'name': 'foo',
        }

        spec2 = {
            'dependencies': {
                'jquery': '~1.11.0',
            },
            'devDependencies': {},
            'name': 'bar',
        }

        answer = {
            'dependencies': {
                'jquery': '~1.11.0',
                'underscore': '~1.8.0',
            },
            'devDependencies': {
                'sinon': '~1.17.0'
            },
        }

        result = cli.generate_merge_dict(
            ('dependencies', 'devDependencies'), spec1, spec2)

        # Naturally, the 'name' is missing and will need to be
        # reconciled separately... will figure this out later.
        self.assertEqual(result, answer)


class CliCheckInteractiveTestCase(unittest.TestCase):

    def test_check_interactive_fail(self):
        self.assertFalse(cli._check_interactive(StringIO(), StringIO()))

    def test_check_interactive_not_stdin(self):
        tempdir = mkdtemp(self)
        fn = join(tempdir, 'test')
        with open(fn, 'w') as fd1:
            self.assertFalse(cli._check_interactive(fd1))

        with open(fn) as fd2:
            self.assertFalse(cli._check_interactive(fd2, fd1))

    @unittest.skipIf(sys.__stdin__.name != '<stdin>', 'stdin is modified')
    def test_check_interactive_good(self):
        self.assertTrue(cli._check_interactive(sys.__stdin__, sys.__stdout__))


class MakeChoiceValidatorTestCase(unittest.TestCase):

    def setUp(self):
        self.validator = cli.make_choice_validator([
            ('foo', 'Foo'),
            ('bar', 'Bar'),
            ('baz', 'Baz'),
            ('YES', 'Yes'),
            ('yes', 'yes'),
        ])

    def test_default_choice(self):
        self.validator = cli.make_choice_validator([
            ('foo', 'Foo'),
            ('bar', 'Bar'),
            ('baz', 'Baz'),
        ], default_key=2)
        self.assertEqual(self.validator(''), 'Baz')

    def test_matched(self):
        self.assertEqual(self.validator('f'), 'Foo')
        self.assertEqual(self.validator('foo'), 'Foo')

    def test_no_normalize(self):
        self.assertEqual(self.validator('Y'), 'Yes')
        self.assertEqual(self.validator('y'), 'yes')

    def test_ambiguous(self):
        with self.assertRaises(ValueError) as e:
            self.validator('ba')

        self.assertEqual(
            str(e.exception), 'Choice ambiguous between (bar, baz)')

    def test_normalized(self):
        validator = cli.make_choice_validator([
            ('Yes', True),
            ('No', False),
        ], normalizer=cli.lower)
        with self.assertRaises(ValueError) as e:
            validator('ba')

        self.assertEqual(
            str(e.exception), 'Invalid choice.')

    def test_null_validator(self):
        # doesn't really belong in this class but similar enough topic
        self.assertEqual(cli.null_validator('test'), 'test')


class CliPromptTestCase(unittest.TestCase):

    def setUp(self):
        self.stdout = StringIO()

    def prompt(self, question, answer,
               validator=None, choices=None,
               default_key=None, normalizer=None):
        stdin = StringIO(answer)
        return cli.prompt(
            question, validator, choices, default_key,
            _stdin=stdin, _stdout=self.stdout)

    def test_prompt_basic(self):
        result = self.prompt('How are you?', 'I am fine thank you.\n')
        self.assertEqual(result, 'I am fine thank you.')

    def test_prompt_basic_choice_overridden(self):
        # Extra choices with a specific validator will not work
        result = self.prompt(
            'How are you?', 'I am fine thank you.\n', choices=(
                ('a', 'A'),
                ('b', 'B'),
                ('c', 'C'),
            ),
            # explicit validator negates the choices
            validator=cli.null_validator,
        )
        self.assertEqual(result, 'I am fine thank you.')
        self.assertEqual(self.stdout.getvalue(), 'How are you? ')

    def test_prompt_choices_only(self):
        # Extra choices with a specific validator will not work
        result = self.prompt(
            'Nice day today.\nHow are you?', 'I am fine thank you.\n',
            choices=(
                ('a', 'A'),
                ('b', 'B'),
                ('c', 'C'),
            ),
            default_key=1,
        )
        self.assertEqual(result, 'B')
        self.assertEqual(
            self.stdout.getvalue(),
            'Nice day today.\n'
            'How are you? (a/b/c) [b] '  # I am fine thank you.\n
            'Invalid choice.\n'
            'How are you? (a/b/c) [b] '
        )

    def test_prompt_choices_canceled(self):
        # Extra choices with a specific validator will not work
        result = self.prompt(
            'How are you?', '', validator=fake_error(KeyboardInterrupt))
        self.assertIsNone(result, None)
        self.assertEqual(
            self.stdout.getvalue(),
            'How are you? Aborted.\n')


class CliDriverTestCase(unittest.TestCase):
    """
    Base cli driver class test case.
    """

    def test_get_bin_version_long(self):
        stub_mod_check_output(self, cli)
        self.check_output_answer = b'Some app v.1.2.3.4. All rights reserved'
        results = cli._get_bin_version('some_app')
        self.assertEqual(results, (1, 2, 3, 4))

    def test_get_bin_version_longer(self):
        stub_mod_check_output(self, cli)
        # tags are ignored for now.
        self.check_output_answer = b'version.11.200.345.4928-what'
        results = cli._get_bin_version('some_app')
        self.assertEqual(results, (11, 200, 345, 4928))

    def test_get_bin_version_short(self):
        stub_mod_check_output(self, cli)
        self.check_output_answer = b'1'
        results = cli._get_bin_version('some_app')
        self.assertEqual(results, (1,))

    def test_get_bin_version_unexpected(self):
        stub_mod_check_output(self, cli)
        self.check_output_answer = b'Nothing'
        results = cli._get_bin_version('some_app')
        self.assertIsNone(results)

    def test_get_bin_version_no_bin(self):
        stub_mod_check_output(self, cli, fake_error(OSError))
        results = cli._get_bin_version('some_app')
        self.assertIsNone(results)

    def test_node_no_path(self):
        stub_os_environ(self)
        os.environ['PATH'] = ''
        self.assertIsNone(cli.get_node_version())

    def test_node_version_mocked(self):
        stub_mod_check_output(self, cli)
        self.check_output_answer = b'v0.10.25'
        version = cli.get_node_version()
        self.assertEqual(version, (0, 10, 25))

    # live test, no stubbing
    @unittest.skipIf(cli.get_node_version() is None, 'Node.js not found.')
    def test_node_version_get(self):
        version = cli.get_node_version()
        self.assertIsNotNone(version)

    def test_node_run_no_path(self):
        stub_os_environ(self)
        os.environ['PATH'] = ''
        with self.assertRaises(OSError):
            cli.node('process.stdout.write("Hello World!");')

    # live test, no stubbing
    @unittest.skipIf(cli.get_node_version() is None, 'Node.js not found.')
    def test_node_run(self):
        stdout, stderr = cli.node('process.stdout.write("Hello World!");')
        self.assertEqual(stdout, 'Hello World!')
        stdout, stderr = cli.node(b'process.stdout.write("Hello World!");')
        self.assertEqual(stdout, b'Hello World!')
        stdout, stderr = cli.node('window')
        self.assertIn('window is not defined', stderr)

    def test_helper_attr(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        with self.assertRaises(AttributeError) as e:
            driver.no_such_attr_here
        self.assertIn('no_such_attr_here', str(e.exception))
        self.assertIsNot(driver.mgr_init, None)
        self.assertIsNot(driver.get_mgr_version, None)
        driver.mgr_install()
        self.assertEqual(self.call_args, ((['mgr', 'install'],), {}))

    def test_install_arguments(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        driver.pkg_manager_install(args=('--pedantic',))
        self.assertEqual(
            self.call_args, ((['mgr', 'install', '--pedantic'],), {}))

    def test_alternative_install_cmd(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', install_cmd='sync')
        driver.pkg_manager_install()
        self.assertEqual(self.call_args, ((['mgr', 'sync'],), {}))

        # Naturally, the short hand call will be changed.
        driver.mgr_sync(args=('all',))
        self.assertEqual(self.call_args, ((['mgr', 'sync', 'all'],), {}))

    def test_install_other_environ(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        driver.pkg_manager_install(env={'MGR_ENV': 'production'})
        self.assertEqual(self.call_args, ((['mgr', 'install'],), {
            'env': {'MGR_ENV': 'production'},
        }))

    def test_set_node_path(self):
        stub_mod_call(self, cli)
        node_path = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            node_path=node_path, pkg_manager_bin='mgr')

        # ensure env is passed into the call.
        driver.pkg_manager_install()
        self.assertEqual(self.call_args, ((['mgr', 'install'],), {
            'env': {'NODE_PATH': node_path},
        }))

        # will be overridden by instance settings.
        driver.pkg_manager_install(env={
            'PATH': '.',
            'MGR_ENV': 'dev',
            'NODE_PATH': '/tmp/somewhere/else/node_mods',
        })
        self.assertEqual(self.call_args, ((['mgr', 'install'],), {
            'env': {'NODE_PATH': node_path, 'MGR_ENV': 'dev', 'PATH': '.'},
        }))

    def test_predefined_path(self):
        # ensure that the various paths are passed to env or cwd.
        stub_mod_call(self, cli)
        somepath = mkdtemp(self)
        cwd = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', env_path=somepath, working_dir=cwd)
        driver.pkg_manager_install()
        args, kwargs = self.call_args
        self.assertEqual(kwargs['env']['PATH'].split(pathsep)[0], somepath)
        self.assertEqual(kwargs['cwd'], cwd)

    def test_env_path_not_exist(self):
        stub_mod_call(self, cli)
        bad_path = '/no/such/path/for/sure/at/here'
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', env_path=bad_path)
        driver.pkg_manager_install()
        args, kwargs = self.call_args
        self.assertNotEqual(kwargs['env']['PATH'].split(pathsep)[0], bad_path)

    def test_paths_unset(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        driver.pkg_manager_install()
        args, kwargs = self.call_args
        self.assertNotIn('PATH', kwargs)
        self.assertNotIn('cwd', kwargs)

    def test_working_dir_set(self):
        stub_mod_call(self, cli)
        some_cwd = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', working_dir=some_cwd)
        driver.pkg_manager_install()
        args, kwargs = self.call_args
        self.assertNotIn('PATH', kwargs)
        self.assertEqual(kwargs['cwd'], some_cwd)

    def test_set_binary(self):
        stub_mod_call(self, cli)
        driver = cli.PackageManagerDriver(pkg_manager_bin='bower')
        # this will call ``bower install`` instead.
        driver.pkg_manager_install()
        self.assertEqual(self.call_args, ((['bower', 'install'],), {}))

    def test_which_is_none(self):
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        self.assertIsNone(driver.which())
        driver.env_path = mkdtemp(self)
        self.assertIsNone(driver.which())

    def test_which_is_set(self):
        stub_os_environ(self)
        tmpdir = mkdtemp(self)
        # fake an executable
        mgr_bin = join(tmpdir, 'mgr')
        with open(mgr_bin, 'w'):
            pass
        os.chmod(mgr_bin, 0o777)

        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        # With env_path is set
        driver.env_path = tmpdir
        self.assertEqual(driver.which(), mgr_bin)

        driver.env_path = None
        self.assertIsNone(driver.which())

        # with an explicitly defined environ PATH
        os.environ['PATH'] = tmpdir

    def test_set_env_path_with_node_modules_fail(self):
        stub_os_environ(self)
        tmpdir = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', working_dir=tmpdir)
        driver._set_env_path_with_node_modules()
        self.assertIsNone(driver.env_path)

    def test_set_env_path_with_node_modules_warning(self):
        stub_os_environ(self)
        tmpdir = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', working_dir=tmpdir)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            driver._set_env_path_with_node_modules(warn=True)
            self.assertTrue(issubclass(w[-1].category, RuntimeWarning))
            self.assertIn(
                "Unable to locate the 'mgr' binary;", str(w[-1].message))

    def fake_mgr_bin(self):
        tmpdir = mkdtemp(self)
        # fake an executable in node_modules
        bin_dir = join(tmpdir, 'node_modules', '.bin')
        os.makedirs(bin_dir)
        mgr_bin = join(bin_dir, 'mgr')
        with open(mgr_bin, 'w'):
            pass
        os.chmod(mgr_bin, 0o777)
        return tmpdir, bin_dir

    def test_set_env_path_with_node_modules_success(self):
        tmpdir, bin_dir = self.fake_mgr_bin()
        # constructor with an explicit working directory.
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', working_dir=tmpdir)
        self.assertIsNone(driver.env_path)
        driver._set_env_path_with_node_modules()
        self.assertEqual(driver.env_path, bin_dir)
        # should still result in the same thing.
        driver._set_env_path_with_node_modules()
        self.assertEqual(driver.env_path, bin_dir)

    def test_set_env_path_with_node_path_success(self):
        tmpdir, bin_dir = self.fake_mgr_bin()
        # default constructor
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        self.assertIsNone(driver.env_path)
        # using NODE_PATH set to a valid node_modules
        driver.node_path = join(tmpdir, 'node_modules')
        driver._set_env_path_with_node_modules()
        self.assertEqual(driver.env_path, bin_dir)
        # should still result in the same thing.
        driver._set_env_path_with_node_modules()
        self.assertEqual(driver.env_path, bin_dir)

    def test_set_env_path_with_node_path_with_environ(self):
        stub_os_environ(self)
        tmpdir, bin_dir = self.fake_mgr_bin()
        # define a NODE_PATH set to a valid node_modules
        os.environ['NODE_PATH'] = join(tmpdir, 'node_modules')
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        driver._set_env_path_with_node_modules()
        self.assertEqual(driver.env_path, bin_dir)

    def test_set_env_path_with_node_path_multiple_with_environ(self):
        tmp = mkdtemp(self)
        tmp1, bin_dir1 = self.fake_mgr_bin()
        tmp2, bin_dir2 = self.fake_mgr_bin()
        node_path = pathsep.join(
            join(d, 'node_modules') for d in (tmp, tmp1, tmp2))
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', node_path=node_path)
        driver._set_env_path_with_node_modules()
        # First one.  Whether the node modules loads correctly, that's
        # up to the nodejs circus.
        self.assertEqual(driver.env_path, bin_dir1)

        # ensure the kws generated correctly.
        env = driver._gen_call_kws()['env']
        self.assertEqual(env['NODE_PATH'], node_path)
        self.assertEqual(env['PATH'].split(pathsep)[0], bin_dir1)

    def test_driver_run_failure(self):
        # testing for success may actually end up being extremely
        # annoying, so we are going to avoid that and let the integrated
        # subclasses deal with it.
        stub_os_environ(self)
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        os.environ['PATH'] = ''
        with self.assertRaises(OSError):
            driver.run()

    # Helpers for getting a module level default instance up

    def test_driver_create_failure(self):
        with self.assertRaises(TypeError):
            # can't create the parent one as it is not subclassed like
            # the following
            cli.PackageManagerDriver.create()

    def test_driver_create(self):
        class Driver(cli.PackageManagerDriver):
            def __init__(self, **kw):
                kw['pkg_manager_bin'] = 'mgr'
                super(Driver, self).__init__(**kw)

        inst = Driver.create()
        self.assertTrue(isinstance(inst, Driver))

    def test_module_level_driver_create(self):
        class Driver(cli.PackageManagerDriver):
            def __init__(self, **kw):
                kw['pkg_manager_bin'] = 'mgr'
                super(Driver, self).__init__(**kw)

        values = {}

        with warnings.catch_warnings():
            # Don't spat out stderr
            warnings.simplefilter('ignore')
            Driver.create(values)

        # Normally, these will be global names.
        self.assertIn('mgr_install', values)
        self.assertIn('mgr_init', values)
        self.assertIn('get_mgr_version', values)

    # Should really put more tests of these kind in here, but the more
    # concrete implementations have done so.  This weird version here
    # is mostly just for laughs.

    def setup_requirements_json(self):
        # what kind of bizzaro world do the following users live in?
        requirements = {"require": {"setuptools": "25.1.6"}}
        mock_provider = MockProvider({
            'requirements.json': json.dumps(requirements),
        })
        # seriously lolwat?
        mock_dist = pkg_resources.Distribution(
            metadata=mock_provider, project_name='calmpy.pip', version='0.0.0')
        working_set = pkg_resources.WorkingSet()
        working_set.add(mock_dist)
        stub_dist_flatten_egginfo_json(self, [cli], working_set)

    def test_pkg_manager_view(self):
        self.setup_requirements_json()
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
        )
        result = driver.pkg_manager_view('calmpy.pip')
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init(self):
        # we still need a temporary directory, but the difference is
        # that whether the instance contains it or not.
        self.setup_requirements_json()
        remember_cwd(self)
        cwd = mkdtemp(self)
        os.chdir(cwd)

        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
        )
        driver.pkg_manager_init('calmpy.pip', interactive=False)

        target = join(cwd, 'requirements.json')
        self.assertTrue(exists(target))
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_working_dir(self):
        self.setup_requirements_json()
        remember_cwd(self)
        original = mkdtemp(self)
        os.chdir(original)
        cwd = mkdtemp(self)
        target = join(cwd, 'requirements.json')

        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
            working_dir=cwd,
        )
        driver.pkg_manager_init('calmpy.pip', interactive=False)

        self.assertFalse(exists(join(original, 'requirements.json')))
        self.assertTrue(exists(target))

        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_exists_and_overwrite(self):
        self.setup_requirements_json()
        cwd = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
            working_dir=cwd,
        )
        target = join(cwd, 'requirements.json')
        with open(target, 'w') as fd:
            result = json.dump({"require": {}}, fd)

        driver.pkg_manager_init(
            'calmpy.pip', interactive=False, overwrite=False)
        with open(target) as fd:
            result = json.load(fd)
        self.assertNotEqual(result, {"require": {"setuptools": "25.1.6"}})

        driver.pkg_manager_init(
            'calmpy.pip', interactive=False, overwrite=True)
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_merge(self):
        self.setup_requirements_json()
        cwd = mkdtemp(self)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
            working_dir=cwd,
        )
        target = join(cwd, 'requirements.json')
        with open(target, 'w') as fd:
            result = json.dump({"require": {"calmpy": "1.0.0"}}, fd)

        driver.pkg_manager_init(
            'calmpy.pip', interactive=False, merge=True, overwrite=True)
        self.assertNotEqual(result, {
            "require": {
                "calmpy": "1.0.0",
                "setuptools": "25.1.6",
            },
            "name": "calmpy.pip",
        })
