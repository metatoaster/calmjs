# -*- coding: utf-8 -*-
import unittest
import json
import sys
import textwrap
from os.path import join
from subprocess import Popen
from subprocess import PIPE
from distutils.errors import DistutilsSetupError
from setuptools.dist import Distribution

import pkg_resources

from calmjs.module import ModuleRegistry
from calmjs import dist as calmjs_dist
from calmjs.cli import locale
from calmjs.testing.mocks import Mock_egg_info
from calmjs.testing.mocks import MockProvider
from calmjs.testing.utils import make_dummy_dist
from calmjs.testing.utils import mkdtemp
from calmjs.testing.utils import stub_stdouts


class DistTestCase(unittest.TestCase):
    """
    calmjs.dist module test case.
    """

    def setUp(self):
        self.dist = Distribution()
        self.optname = 'default_json'
        self.pkgname = calmjs_dist.DEFAULT_JSON

    def test_is_json_compat_bad_type(self):
        with self.assertRaises(ValueError) as e:
            calmjs_dist.is_json_compat(NotImplemented)

        self.assertEqual(
            str(e.exception),
            'must be a JSON serializable object: '
            'NotImplemented is not JSON serializable'
        )

    def test_is_json_compat_bad_type_in_dict(self):
        with self.assertRaises(ValueError) as e:
            calmjs_dist.is_json_compat({
                'devDependencies': {
                    'left-pad': NotImplemented,
                }
            })

        self.assertEqual(
            str(e.exception),
            'must be a JSON serializable object: '
            'NotImplemented is not JSON serializable'
        )

    def test_is_json_compat_bad_type_not_dict(self):
        with self.assertRaises(ValueError) as e:
            calmjs_dist.is_json_compat(1)

        self.assertEqual(
            str(e.exception),
            'must be specified as a JSON serializable dict '
            'or a JSON deserializable string'
        )

        with self.assertRaises(ValueError) as e:
            calmjs_dist.is_json_compat('"hello world"')

        self.assertEqual(
            str(e.exception),
            'must be specified as a JSON serializable dict '
            'or a JSON deserializable string'
        )

    def test_is_json_compat_bad_encode(self):
        with self.assertRaises(ValueError) as e:
            calmjs_dist.is_json_compat(
                '{'
                '    "devDependencies": {'
                '        "left-pad": "~1.1.1",'  # trailing comma
                '    },'
                '}'
            )

        self.assertTrue(str(e.exception).startswith('JSON decoding error:'))

    def test_is_json_compat_good_str(self):
        result = calmjs_dist.is_json_compat(
            '{'
            '    "devDependencies": {'
            '        "left-pad": "~1.1.1"'
            '    }'
            '}'
        )
        self.assertTrue(result)

    def test_is_json_compat_good_dict(self):
        result = calmjs_dist.is_json_compat(
            # trailing commas are fine in python dicts.
            {
                "devDependencies": {
                    "left-pad": "~1.1.1",
                },
            },
        )
        self.assertTrue(result)

    def test_is_json_compat_good_dict_with_none(self):
        # Possible to specify a null requirement to remove things.
        result = calmjs_dist.is_json_compat(
            {
                "devDependencies": {
                    "left-pad": None
                },
            },
        )
        self.assertTrue(result)

    def test_validate_json_field_good(self):
        # don't need to validate against None as "the validation
        # function will only be called if the setup() call sets it to a"
        # non-None value", as per setuptools documentation.

        self.assertTrue(calmjs_dist.validate_json_field(
            self.dist, self.optname, {}))

    def test_validate_json_field_bad(self):
        with self.assertRaises(DistutilsSetupError) as e:
            calmjs_dist.validate_json_field(
                self.dist, self.optname, "{},")

        self.assertTrue(str(e.exception).startswith(
            "'default_json' JSON decoding error:"
        ))

    def test_write_json_file(self):
        self.dist.default_json = '{}'
        ei = Mock_egg_info(self.dist)
        ei.initialize_options()
        calmjs_dist.write_json_file(
            'default_json', ei, self.pkgname, self.pkgname)
        self.assertEqual(ei.called[self.pkgname], '{}')

    def test_write_json_file_dict(self):
        self.dist.default_json = {}
        ei = Mock_egg_info(self.dist)
        ei.initialize_options()
        calmjs_dist.write_json_file(
            'default_json', ei, self.pkgname, self.pkgname)
        self.assertEqual(ei.called[self.pkgname], '{}')

    def test_write_json_file_delete(self):
        self.dist.default_json = None  # this triggers the delete
        ei = Mock_egg_info(self.dist)
        ei.initialize_options()
        calmjs_dist.write_json_file(
            'default_json', ei, self.pkgname, self.pkgname)
        # However since the top level method was stubbed out, just check
        # that it's been called...
        self.assertEqual(ei.called[self.pkgname], None)

    def test_find_pkg_dist(self):
        # Only really testing that this returns an actual distribution
        result = calmjs_dist.find_pkg_dist('setuptools')
        # it's the Distribution class from pkg_resources...
        self.assertTrue(isinstance(result, pkg_resources.Distribution))
        self.assertEqual(result.project_name, 'setuptools')

    def test_convert_package_names(self):
        result, error = calmjs_dist.convert_package_names('setuptools calmjs')
        self.assertEqual(result, ['setuptools', 'calmjs'])
        self.assertEqual(error, [])

        result, error = calmjs_dist.convert_package_names('calmjs [dev]')
        self.assertEqual(result, ['calmjs'])
        self.assertEqual(error, ['[dev]'])

        result, error = calmjs_dist.convert_package_names('calmjs[dev]')
        self.assertEqual(result, ['calmjs[dev]'])
        self.assertEqual(error, [])

        result, error = calmjs_dist.convert_package_names(
            ['setuptools'])
        self.assertEqual(result, ['setuptools'])
        self.assertEqual(error, [])

        result, error = calmjs_dist.convert_package_names(
            ['setuptools', '[dev]', 'calmjs [dev]'])
        self.assertEqual(result, ['setuptools', 'calmjs [dev]'])
        self.assertEqual(error, ['[dev]'])

    def test_get_pkg_json_integrated_live(self):
        # Try reading a fake package.json from setuptools package
        # directly and see that it will just return nothing while not
        # exploding.
        self.assertIsNone(calmjs_dist.read_egginfo_json(
            'setuptools', filename='_not_package.json'))

    def test_read_dist_egginfo_json(self):
        package_json = {"dependencies": {"left-pad": "~1.1.1"}}

        # We will mock up a Distribution object with some fake metadata.
        mock_provider = MockProvider({
            self.pkgname: json.dumps(package_json),
        })

        mock_dist = pkg_resources.Distribution(
            metadata=mock_provider, project_name='dummydist', version='0.0.0')

        results = calmjs_dist.read_dist_egginfo_json(mock_dist)

        self.assertEqual(results, package_json)

    def test_get_dist_package_decoding_error(self):
        # Quiet stdout from distutils logs
        stub_stdouts(self)

        # trailing comma
        package_json = '{"dependencies": {"left-pad": "~1.1.1"},}'
        # bad data could be created by a competiting package.
        mock_provider = MockProvider({
            self.pkgname: package_json,
        })
        mock_dist = pkg_resources.Distribution(
            metadata=mock_provider, project_name='dummydist', version='0.0.0')

        results = calmjs_dist.read_dist_egginfo_json(mock_dist)

        # Should still not fail.
        self.assertIsNone(results)

    def test_get_dist_package_read_error(self):
        # Quiet stdout from distutils logs
        stub_stdouts(self)

        mock_provider = MockProvider({
            self.pkgname: None,  # None will emulate IO error.
        })
        mock_dist = pkg_resources.Distribution(
            metadata=mock_provider, project_name='dummydist', version='0.0.0')
        results = calmjs_dist.read_dist_egginfo_json(mock_dist)
        # Should still not fail.
        self.assertIsNone(results)

    def test_get_dist_package_fs(self):
        """
        Use the make_dummy_dist testing util to generate a working
        distribution based on upstream library.
        """

        package_json = {"dependencies": {"left-pad": "~1.1.1"}}
        mock_dist = make_dummy_dist(
            self, (
                (self.pkgname, json.dumps(package_json)),
            ), pkgname='dummydist'
        )
        results = calmjs_dist.read_dist_egginfo_json(mock_dist)
        self.assertEqual(results['dependencies']['left-pad'], '~1.1.1')

    def test_read_dist_egginfo_json_alternative_name_args(self):
        package_json = {"dependencies": {"left-pad": "~1.1.1"}}

        # We will mock up a Distribution object with some fake metadata.
        mock_provider = MockProvider({
            'bower.json': json.dumps(package_json),
        })

        mock_dist = pkg_resources.Distribution(
            metadata=mock_provider, project_name='dummydist', version='0.0.0')

        results = calmjs_dist.read_dist_egginfo_json(
            mock_dist, filename='bower.json')

        self.assertEqual(results, package_json)

        working_set = pkg_resources.WorkingSet()
        working_set.add(mock_dist)

        self.assertEqual(package_json, calmjs_dist.read_egginfo_json(
            'dummydist', filename='bower.json', working_set=working_set))

        # Finally do the flattening
        flattened_json = {
            "dependencies": {"left-pad": "~1.1.1"}, "devDependencies": {}}
        self.assertEqual(flattened_json, calmjs_dist.flatten_dist_egginfo_json(
            [mock_dist], filename='bower.json', working_set=working_set))
        self.assertEqual(flattened_json, calmjs_dist.flatten_egginfo_json(
            ['dummydist'], filename='bower.json', working_set=working_set))

    def tests_flatten_egginfo_json_deps(self):
        # Quiet stdout from distutils logs
        stub_stdouts(self)
        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
            ])),
            (self.pkgname, 'This is very NOT a package.json.'),
        ), 'security', '9999')

        framework = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'security',
            ])),
            (self.pkgname, json.dumps({
                'name': 'framework',
                'description': 'some framework',
                'dependencies': {
                    'left-pad': '~1.1.1',
                },
                'devDependencies': {
                    'sinon': '~1.15.0',
                },
            })),
        ), 'framework', '2.4')

        widget = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
            ])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'jquery': '~2.0.0',
                    'underscore': '~1.7.0',
                },
            })),
        ), 'widget', '1.1')

        forms = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.2',
                'widget>=1.0',
            ])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'backbone': '~1.3.0',
                    'jquery-ui': '~1.12.0',
                },
            })),
        ), 'forms', '1.6')

        service = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
            ])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'underscore': '~1.8.0',
                },
                'devDependencies': {
                    'sinon': '~1.17.0',
                },
            })),
        ), 'service', '1.1')

        site = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
                'widget>=1.1',
                'forms>=1.6',
                'service>=1.1',
            ])),
            (self.pkgname, json.dumps({
                'name': 'site',
                'dependencies': {
                    'underscore': '~1.8.0',
                    'jquery': '~1.9.0',
                },
            })),
        ), 'site', '2.0')

        answer = {
            'name': 'site',
            'dependencies': {
                'left-pad': '~1.1.1',
                'jquery': '~1.9.0',
                'backbone': '~1.3.0',
                'jquery-ui': '~1.12.0',
                'underscore': '~1.8.0',
            },
            'devDependencies': {
                'sinon': '~1.17.0',
            },
        }

        # WorkingSet is a frozen representation of the versions and
        # locations of all available package presented through sys.path
        # by default.  Here we just emulate it using our temporary path
        # created by our mock package definitions above.

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        # Ensure that this works with a raw requirements object, that
        # should normally be automatically resolved from a name.
        result = calmjs_dist.flatten_dist_egginfo_json(
            [framework, widget, forms, service, site], working_set=working_set)
        self.assertEqual(result, answer)

        # Also a raw requirement (package) string on the other function.
        result = calmjs_dist.flatten_egginfo_json(
            ['site'], working_set=working_set)
        self.assertEqual(result, answer)

    def tests_flatten_egginfo_json_multi_version(self):
        """
        Need to ensure the *correct* version is picked.
        """

        uilib_1_1 = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([])),
            (self.pkgname, json.dumps({
                'dependencies': {'jquery': '~1.0.0'},
            })),
        ), 'uilib', '1.1.0')

        uilib_1_4 = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([])),
            (self.pkgname, json.dumps({
                'dependencies': {'jquery': '~1.4.0'},
            })),
        ), 'uilib', '1.4.0')

        uilib_1_9 = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([])),
            (self.pkgname, json.dumps({
                'dependencies': {'jquery': '~1.9.0'},
            })),
        ), 'uilib', '1.9.0')

        app = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'uilib>=1.0',
            ])),
        ), 'app', '2.0')

        # Instead of passing in the tmpdir like the previous test, this
        # working set will be manually created as the situation here
        # should not happen normally - a raw (dist|site)-packages dir
        # with multiple versions of egg-info available for a single
        # importable path - a situation that results in the uilib's
        # actual version being ambiguous.  Anyway, each of these
        # "versions" should be in their own .egg directory with an
        # "EGG-INFO" subdir underneath, with the top level egg path
        # being added to sys.path either through a site.py or some kind
        # of generated program entry point that does that.  For all
        # intents and purposes if the manual Requirements are added to
        # the WorkingSet like so, the expected values presented in the
        # system can be created to behave as if they really exist.

        working_set = pkg_resources.WorkingSet()
        working_set.add(uilib_1_9, self._calmjs_testing_tmpdir)
        working_set.add(app, self._calmjs_testing_tmpdir)

        answer = {
            'dependencies': {
                'jquery': '~1.9.0',
            },
            'devDependencies': {},
        }
        result = calmjs_dist.flatten_egginfo_json(
            ['app'], working_set=working_set)
        self.assertEqual(result, answer)

        # Now emulate an older version, with a different working set.

        working_set = pkg_resources.WorkingSet()
        working_set.add(uilib_1_4, self._calmjs_testing_tmpdir)
        # this shouldn't override the previous.
        working_set.add(uilib_1_1, self._calmjs_testing_tmpdir)
        working_set.add(app, self._calmjs_testing_tmpdir)

        answer = {
            'dependencies': {
                'jquery': '~1.4.0',
            },
            'devDependencies': {},
        }
        result = calmjs_dist.flatten_egginfo_json(
            ['app'], working_set=working_set)
        self.assertEqual(result, answer)

    def tests_flatten_egginfo_json_missing_complete(self):
        """
        A completely missing egg should not just blow up.
        """

        working_set = pkg_resources.WorkingSet()
        self.assertEqual(
            {'dependencies': {}, 'devDependencies': {}},
            calmjs_dist.flatten_egginfo_json(
                'nosuchpkg', working_set=working_set))

    def tests_flatten_egginfo_json_missing_deps(self):
        """
        Missing dependencies should not cause a hard failure.
        """

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'uilib>=1.0',
            ])),
        ), 'app', '2.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        # Python dependency acquisition failures should fail hard.
        with self.assertRaises(pkg_resources.DistributionNotFound):
            calmjs_dist.flatten_egginfo_json(['app'], working_set=working_set)

    def tests_flatten_egginfo_json_nulled(self):
        """
        Need to ensure the *correct* version is picked.
        """

        lib = make_dummy_dist(self, (  # noqa: F841
            ('requires.txt', '\n'.join([])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'jquery': '~3.0.0',
                    'left-pad': '1.1.1',
                },
            })),
        ), 'lib', '1.0.0')

        app = make_dummy_dist(self, (  # noqa: F841
            ('requires.txt', '\n'.join([
                'lib>=1.0.0',
            ])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'jquery': '~3.0.0',
                    'left-pad': None,
                },
            })),
        ), 'app', '2.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        answer = {
            'dependencies': {
                'jquery': '~3.0.0',
                # left-pad will be absent as app removed via None.
            },
            'devDependencies': {},
        }
        result = calmjs_dist.flatten_egginfo_json(
            ['app'], working_set=working_set)
        self.assertEqual(result, answer)

    # While it really is for node/npm, the declaration is almost generic
    # enough that the particular method should be used here.
    def test_node_modules_registry_flattening(self):
        lib = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'jquery': '~1.8.3',
                    'underscore': '1.8.3',
                },
            })),
            ('extras_calmjs.json', json.dumps({
                'node_modules': {
                    'jquery': 'jquery/dist/jquery.js',
                    'underscore': 'underscore/underscore-min.js',
                },
                'something_else': {'parent': 'lib'},
            })),
        ), 'lib', '1.0.0')

        app = make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'lib>=1.0.0',
            ])),
            (self.pkgname, json.dumps({
                'dependencies': {
                    'jquery': '~3.0.0',
                },
            })),
            ('extras_calmjs.json', json.dumps({
                'node_modules': {
                    'jquery': 'jquery/dist/jquery.min.js',
                },
                'something_else': {'child': 'named'},
            })),
        ), 'app', '2.0')

        working_set = pkg_resources.WorkingSet()
        working_set.add(lib, self._calmjs_testing_tmpdir)
        working_set.add(app, self._calmjs_testing_tmpdir)

        self.assertEqual(1, len(calmjs_dist.pkg_names_to_dists(
            ['app'], working_set=working_set)))

        single = calmjs_dist.get_extras_calmjs(
            ['app'], working_set=working_set)
        self.assertEqual(single['node_modules'], {
            'jquery': 'jquery/dist/jquery.min.js',
        })

        self.assertEqual(2, len(calmjs_dist.find_packages_requirements_dists(
            ['app'], working_set=working_set)))

        results = calmjs_dist.flatten_extras_calmjs(
            ['app'], working_set=working_set)
        self.assertEqual(results['node_modules'], {
            'jquery': 'jquery/dist/jquery.min.js',
            'underscore': 'underscore/underscore-min.js',
        })
        # child takes precedences as this was not specified to be merged
        self.assertEqual(results['something_else'], {'child': 'named'})

    def test_module_registry_dependencies_failure_no_reg(self):
        self.assertEqual(calmjs_dist.flatten_module_registry_dependencies(
            ['calmjs'], registry_key='calmjs.no_reg',), {})

        self.assertEqual(calmjs_dist.get_module_registry_dependencies(
            ['calmjs'], registry_key='calmjs.no_reg',), {})

    def test_module_registry_dependencies_success(self):
        from calmjs.registry import _inst

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
            ])),
        ), 'security', '9999')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'security',
            ])),
        ), 'framework', '2.4')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
            ])),
        ), 'widget', '1.1')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.2',
                'widget>=1.0',
            ])),
        ), 'forms', '1.6')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
            ])),
        ), 'service', '1.1')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'framework>=2.1',
                'widget>=1.1',
                'forms>=1.6',
                'service>=1.1',
            ])),
        ), 'site', '2.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        dummy_regid = 'calmjs.module.dummy.test'

        # ensure the dummy record we adding will be cleaned up.
        def cleanup():
            _inst.records.pop(dummy_regid, None)
        self.addCleanup(cleanup)

        # set up/register a dummy registry with dummy records.
        dummy_reg = _inst.records[dummy_regid] = ModuleRegistry(dummy_regid)
        dummy_reg.records = {
            'site': {
                'site/config': '/home/src/site/config.js',
            },
            'widget': {
                'widget/ui': '/home/src/widget/ui.js',
                'widget/widget': '/home/src/widget/widget.js',
            },
            'forms': {
                'forms/ui': '/home/src/forms/ui.js',
            },
            'service': {
                'service/lib': '/home/src/forms/lib.js',
            },
        }
        dummy_reg.package_module_map = {
            'site': ['site'],
            'widget': ['widget'],
            'forms': ['forms'],
            'service': ['service'],
        }

        site = calmjs_dist.flatten_module_registry_dependencies(
            ['site'], registry_key=dummy_regid, working_set=working_set)
        self.assertEqual(site, {
            'site/config': '/home/src/site/config.js',
            'widget/ui': '/home/src/widget/ui.js',
            'widget/widget': '/home/src/widget/widget.js',
            'service/lib': '/home/src/forms/lib.js',
            'forms/ui': '/home/src/forms/ui.js',
        })

        service = calmjs_dist.flatten_module_registry_dependencies(
            ['service'], registry_key=dummy_regid, working_set=working_set)
        self.assertEqual(service, {
            'service/lib': '/home/src/forms/lib.js',
        })

        forms = calmjs_dist.flatten_module_registry_dependencies(
            ['forms'], registry_key=dummy_regid, working_set=working_set)
        self.assertEqual(forms, {
            'forms/ui': '/home/src/forms/ui.js',
            'widget/ui': '/home/src/widget/ui.js',
            'widget/widget': '/home/src/widget/widget.js',
        })

        # merger
        merged = calmjs_dist.flatten_module_registry_dependencies(
            ['forms', 'service'], registry_key=dummy_regid,
            working_set=working_set)
        self.assertEqual(merged, {
            'forms/ui': '/home/src/forms/ui.js',
            'widget/ui': '/home/src/widget/ui.js',
            'widget/widget': '/home/src/widget/widget.js',
            'service/lib': '/home/src/forms/lib.js',
        })

        # no declared exports/registry entries in security.
        security = calmjs_dist.flatten_module_registry_dependencies(
            ['security'], registry_key=dummy_regid, working_set=working_set)
        self.assertEqual(security, {})

        # package not even in working set
        missing_pkg = calmjs_dist.flatten_module_registry_dependencies(
            ['missing_pkg'], registry_key=dummy_regid, working_set=working_set)
        self.assertEqual(missing_pkg, {})

        # singlular methods
        self.assertEqual(calmjs_dist.get_module_registry_dependencies(
            ['site'], registry_key=dummy_regid, working_set=working_set), {
            'site/config': '/home/src/site/config.js'})

        self.assertEqual(calmjs_dist.get_module_registry_dependencies(
            ['security'],
            registry_key=dummy_regid, working_set=working_set), {})

        self.assertEqual(calmjs_dist.get_module_registry_dependencies(
            ['missing'],
            registry_key=dummy_regid, working_set=working_set), {})


class DistIntegrationTestCase(unittest.TestCase):
    """
    Testing integration of dist with the rest of calmjs and setuptools.
    """

    def setUp(self):
        """
        Set up the dummy test files.
        """

        self.pkg_root = mkdtemp(self)
        setup_py = join(self.pkg_root, 'setup.py')
        dummy_pkg = join(self.pkg_root, 'dummy_pkg.py')

        contents = (
            (setup_py, '''
                from setuptools import setup
                setup(
                    py_modules=['dummy_pkg'],
                    name='dummy_pkg',
                    package_json={
                        'dependencies': {
                            'jquery': '~3.0.0',
                        },
                    },
                    extras_calmjs={
                        'node_modules': {
                            'jquery': 'jquery/dist/jquery.js',
                        },
                    },
                    zip_safe=False,
                )
            '''),
            (dummy_pkg, '''
            foo = 'bar'
            '''),
        )

        for fn, content in contents:
            with open(fn, 'w') as fd:
                fd.write(textwrap.dedent(content).lstrip())

    def test_setup_egg_info(self):
        """
        Emulate the execution of ``python setup.py egg_info``.

        Ensure everything is covered.
        """

        # naturally, run it like we mean it.
        p = Popen(
            [sys.executable, 'setup.py', 'egg_info'], stdout=PIPE, stderr=PIPE,
            cwd=self.pkg_root,
        )
        stdout, stderr = p.communicate()
        stdout = stdout.decode(locale)
        self.assertIn('writing package_json', stdout)
        self.assertIn('writing extras_calmjs', stdout)

        egg_root = join(self.pkg_root, 'dummy_pkg.egg-info')

        with open(join(egg_root, 'package.json')) as fd:
            self.assertEqual(json.load(fd), {
                'dependencies': {
                    'jquery': '~3.0.0',
                },
            })

        with open(join(egg_root, 'extras_calmjs.json')) as fd:
            self.assertEqual(json.load(fd), {
                'node_modules': {
                    'jquery': 'jquery/dist/jquery.js',
                },
            })
