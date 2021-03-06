# -*- coding: utf-8 -*-
"""
Module for the integration with distutils/setuptools.

Provides functions and classes that enable the management of npm
dependencies for JavaScript sources that lives in Python packages.
"""

from __future__ import absolute_import
import json

from functools import partial
from logging import getLogger

from distutils.errors import DistutilsSetupError

from pkg_resources import Requirement
from pkg_resources import working_set as default_working_set

from calmjs.registry import get
from calmjs.base import BaseModuleRegistry

logger = getLogger(__name__)

# default package definition filename.
DEFAULT_JSON = 'default.json'
EXTRAS_CALMJS_FIELD = 'extras_calmjs'
EXTRAS_CALMJS_JSON = 'extras_calmjs.json'
DEP_KEYS = ('dependencies', 'devDependencies')


def is_json_compat(value):
    """
    Check that the value is either a JSON decodable string or a dict
    that can be encoded into a JSON.

    Raises ValueError when validation fails.
    """

    try:
        value = json.loads(value)
    except ValueError as e:
        raise ValueError('JSON decoding error: ' + str(e))
    except TypeError:
        # Check that the value can be serialized back into json.
        try:
            json.dumps(value)
        except TypeError as e:
            raise ValueError(
                'must be a JSON serializable object: ' + str(e))

    if not isinstance(value, dict):
        raise ValueError(
            'must be specified as a JSON serializable dict or a '
            'JSON deserializable string'
        )

    return True


def validate_json_field(dist, attr, value):
    """
    Check for json validity.
    """

    try:
        is_json_compat(value)
    except ValueError as e:
        raise DistutilsSetupError("%r %s" % (attr, e))

    return True


def write_json_file(argname, cmd, basename, filename):
    """
    Write JSON captured from the defined argname into the package's
    egg-info directory using the specified filename.
    """

    value = getattr(cmd.distribution, argname, None)

    if isinstance(value, dict):
        value = json.dumps(
            value, indent=4, sort_keys=True, separators=(',', ': '))

    cmd.write_or_delete_file(argname, filename, value, force=True)


def find_pkg_dist(pkg_name, working_set=None):
    """
    Locate a package's distribution by its name.
    """

    working_set = working_set or default_working_set
    req = Requirement.parse(pkg_name)
    return working_set.find(req)


def convert_package_names(package_names):
    """
    Convert package names, which can be a string of a number of package
    names or requirements separated by spaces.
    """

    results = []
    errors = []

    for name in (
            package_names.split()
            if hasattr(package_names, 'split') else package_names):
        try:
            Requirement.parse(name)
        except ValueError:
            errors.append(name)
        else:
            results.append(name)

    return results, errors


def pkg_names_to_dists(pkg_names, working_set=None):
    working_set = working_set or default_working_set
    return [
        find_pkg_dist(pkg_name, working_set=working_set)
        for pkg_name in pkg_names
    ]


def find_packages_requirements_dists(pkg_names, working_set=None):
    """
    Return the entire list of dependency requirements, reversed from the
    bottom.
    """

    working_set = working_set or default_working_set
    requirements = [
        r for r in (Requirement.parse(req) for req in pkg_names)
        if working_set.find(r)
    ]
    return list(reversed(working_set.resolve(requirements)))


def read_dist_egginfo_json(dist, filename=DEFAULT_JSON):
    """
    Safely get a json within an egginfo from a distribution.
    """

    # use the given package's distribution to acquire the json file.
    if not dist.has_metadata(filename):
        logger.debug("no '%s' for '%s'", filename, dist)
        return

    try:
        result = dist.get_metadata(filename)
    except IOError:
        logger.error("I/O error on reading of '%s' for '%s'.", filename, dist)
        return

    try:
        obj = json.loads(result)
    except (TypeError, ValueError):
        logger.error(
            "the '%s' found in '%s' is not a valid json.", filename, dist)
        return

    logger.debug("found '%s' for '%s'.", filename, dist)
    return obj


def read_egginfo_json(pkg_name, filename=DEFAULT_JSON, working_set=None):
    """
    Read json from egginfo of a package identified by `pkg_name` that's
    already installed within the current Python environment.
    """

    working_set = working_set or default_working_set
    dist = find_pkg_dist(pkg_name, working_set=working_set)
    return read_dist_egginfo_json(dist, filename)


def flatten_dist_egginfo_json(
        source_dists, filename=DEFAULT_JSON, dep_keys=DEP_KEYS,
        working_set=None):
    """
    Flatten a distribution's egginfo json, with the depended keys to be
    flattened.

    Originally this was done for this:

    Resolve a distribution's (dev)dependencies through the working set
    and generate a flattened version package.json, returned as a dict,
    from the resolved distributions.

    Default working set is the one from pkg_resources.

    The generated package.json dict is done by grabbing all package.json
    metadata from all parent Python packages, starting from the highest
    level and down to the lowest.  The current distribution's
    dependencies will be layered on top along with its other package
    information.  This has the effect of child packages overriding
    node/npm dependencies which is by the design of this function.  If
    nested dependencies are desired, just rely on npm only for all
    dependency management.

    Flat is better than nested.
    """

    working_set = working_set or default_working_set
    obj = {}

    # TODO figure out the best way to explicitly report back to caller
    # how the keys came to be (from which dist).  Perhaps create a
    # detailed function based on this, retain this one to return the
    # distilled results.

    depends = {dep: {} for dep in dep_keys}

    # Go from the earliest package down to the latest one, as we will
    # flatten children's d(evD)ependencies on top of parent's.
    for dist in source_dists:
        obj = read_dist_egginfo_json(dist, filename)
        if not obj:
            continue

        logger.debug("merging '%s' for required '%s'", filename, dist)
        for dep in dep_keys:
            depends[dep].update(obj.get(dep, {}))

    if obj is None:
        # top level object does not have egg-info defined
        return depends

    for dep in dep_keys:
        # filtering out all the nulls.
        obj[dep] = {k: v for k, v in depends[dep].items() if v is not None}

    return obj


def flatten_egginfo_json(
        pkg_names, filename=DEFAULT_JSON, dep_keys=DEP_KEYS, working_set=None):
    """
    A shorthand calling convention where the package name is supplied
    instead of a distribution.

    Originally written for this:

    Generate a flattened package.json with packages `pkg_names` that are
    already installed within the current Python environment (defaults
    to the current global working_set which should have been set up
    correctly by pkg_resources).
    """

    working_set = working_set or default_working_set
    # Ensure only grabbing packages that exists in working_set
    dists = find_packages_requirements_dists(
        pkg_names, working_set=working_set)
    return flatten_dist_egginfo_json(
        dists, filename=filename, dep_keys=dep_keys, working_set=working_set)


# Default calmjs core implementation specific functions, to be used by
# integrators intended to use this as a distribution.

def get_extras_calmjs(pkg_names, working_set=None):
    """
    Only extract the extras_calmjs information for the given packages
    'pkg_names'.
    """

    working_set = working_set or default_working_set
    dep_keys = set(get('calmjs.extras_keys').iter_records())
    dists = pkg_names_to_dists(pkg_names, working_set=working_set)
    return flatten_dist_egginfo_json(
        dists, filename=EXTRAS_CALMJS_JSON,
        dep_keys=dep_keys, working_set=working_set
    )


def flatten_extras_calmjs(pkg_names, working_set=None):
    """
    Traverses through the dependency graph of packages 'pkg_names' and
    flattens all the egg_info calmjs registry information.
    """

    working_set = working_set or default_working_set
    # registry key must be explicit here as it was designed for this.
    dep_keys = set(get('calmjs.extras_keys').iter_records())
    dists = find_packages_requirements_dists(
        pkg_names, working_set=working_set)
    return flatten_dist_egginfo_json(
        dists, filename=EXTRAS_CALMJS_JSON,
        dep_keys=dep_keys, working_set=working_set
    )

write_extras_calmjs = partial(write_json_file, EXTRAS_CALMJS_FIELD)


def get_module_registry_dependencies(
        pkg_names, registry_key='calmjs.module', working_set=None):
    """
    For the given packages 'pkg_names' and the registry identified by
    'registry_key', resolve the exported location for just the package.
    """

    working_set = working_set or default_working_set
    registry = get(registry_key)
    if not isinstance(registry, BaseModuleRegistry):
        return {}
    result = {}
    for pkg_name in pkg_names:
        result.update(registry.get_records_for_package(pkg_name))
    return result


def flatten_module_registry_dependencies(
        pkg_names, registry_key='calmjs.module', working_set=None):
    """
    For the given packages 'pkg_names' and the registry identified by
    'registry_key', resolve and flatten all the exported locations.
    """

    working_set = working_set or default_working_set
    result = {}
    registry = get(registry_key)
    if not isinstance(registry, BaseModuleRegistry):
        return result

    dists = find_packages_requirements_dists(
        pkg_names, working_set=working_set)
    for dist in dists:
        result.update(registry.get_records_for_package(dist.project_name))

    return result
