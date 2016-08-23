# -*- coding: utf-8 -*-
import logging
import sys
from argparse import ArgumentParser

from pkg_resources import working_set as default_working_set

CALMJS_RUNTIME = 'calmjs.runtime'
logger = logging.getLogger(__name__)
pkg_manager_options = (
    ('init', None,
     "action: generate and write '%(pkgdef_filename)s' to the "
     "current directory for this Python package"),
    # this required implicit step is done, otherwise there are no
    # difference to running ``npm init`` directly from the shell.
    ('install', None,
     "action: run '%(pkg_manager_bin)s install' with generated "
     "'%(pkgdef_filename)s'; implies init; will abort if init fails "
     "to write the generated file"),
    # as far as I know typically setuptools setup.py are not
    # interactive, so we keep it that way unless user explicitly
    # want this.
    ('interactive', 'i',
     "enable interactive prompt; if an action requires an explicit "
     "response but none were specified through flags "
     "(i.e. overwrite), prompt for response; disabled by default"),
    ('merge', 'm',
     "merge generated 'package.json' with the one in current "
     "directory; if interactive mode is not enabled, implies "
     "overwrite, else the difference will be displayed"),
    ('overwrite', 'w',
     "automatically overwrite any file changes to current directory "
     "without prompting"),
)
DEST_ACTION = 'action'
DEST_RUNTIME = 'runtime'


def make_cli_options(cli_driver):
    return [
        (full, s, desc % {
            'pkgdef_filename': cli_driver.pkgdef_filename,
            'pkg_manager_bin': cli_driver.pkg_manager_bin,
        }) for full, s, desc in pkg_manager_options
    ]


class Runtime(object):
    """
    calmjs runtime collection
    """

    def __init__(self, working_set=default_working_set):
        self.working_set = working_set
        self.argparser = None
        self.runtimes = {}
        self.init()

    def init(self):
        if self.argparser is None:
            self.argparser = ArgumentParser(description=self.__doc__)
            self.init_argparser(self.argparser)

    def init_argparser(self, argparser):
        commands = argparser.add_subparsers(
            dest=DEST_RUNTIME, metavar='<command>')

        for entry_point in self.working_set.iter_entry_points(CALMJS_RUNTIME):
            try:
                # load the runtime instance
                inst = entry_point.load()
            except ImportError:
                logger.exception(
                    "bad '%s' entry point '%s' from '%s'",
                    CALMJS_RUNTIME, entry_point, entry_point.dist,
                )
                continue

            if not isinstance(inst, DriverRuntime):
                logger.error(
                    "bad '%s' entry point '%s' from '%s': "
                    "not a calmjs.runtime.DriverRuntime instance.",
                    CALMJS_RUNTIME, entry_point, entry_point.dist,
                )
                continue

            subparser = commands.add_parser(
                entry_point.name,
                help=inst.cli_driver.description,
            )
            self.runtimes[entry_point.name] = inst
            inst.init_argparser(subparser)

    def run(self, **kwargs):
        runtime = self.runtimes.get(kwargs.pop(DEST_RUNTIME))
        if runtime:
            runtime.run(**kwargs)
        # nothing is going to happen otherwise?

    def __call__(self, args):
        kwargs = vars(self.argparser.parse_args(args))
        self.run(**kwargs)


class DriverRuntime(Runtime):
    """
    runtime for driver
    """

    def __init__(self, cli_driver, *a, **kw):
        self.cli_driver = cli_driver
        super(DriverRuntime, self).__init__(*a, **kw)

    def init_argparser(self, argparser=None):
        """
        DriverRuntime should have their own init_argparer method.
        """

    def run(self, **kwargs):
        """
        DriverRuntime should have their own running method.
        """


class PackageManagerRuntime(DriverRuntime):
    """
    A calmjs runtime

    e.g

    $ calmjs npm --init example.package
    $ calmjs npm --install example.package
    """

    def init(self):
        self.pkg_manager_options = make_cli_options(self.cli_driver)
        super(PackageManagerRuntime, self).init()

    def init_argparser(self, argparser):
        # provide this for the setuptools command class.
        actions = argparser.add_argument_group('actions arguments')

        for full, short, desc in self.pkg_manager_options:
            args = [
                dash + key
                for dash, key in zip(('-', '--'), (short, full))
                if key
            ]
            if not short:
                f = getattr(self.cli_driver, '%s_%s' % (
                    self.cli_driver.binary, full), None)
                if callable(f):
                    actions.add_argument(
                        *args, help=desc, action='store_const',
                        dest=DEST_ACTION, const=f
                    )
                    continue
            argparser.add_argument(*args, help=desc, action='store_true')

        argparser.add_argument(
            'package_name', help='Name of the python package to use')

    def run(self, **kwargs):
        action = kwargs.pop(DEST_ACTION)
        action(**kwargs)


def main(args=None):
    runtime = Runtime()
    runtime(args or sys.argv[1:])