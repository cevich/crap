#!/usr/bin/env python2

"""
Dynamic inventory script + action-plugin for static inventory and fact cache management

Expected to be an argument to the ansible-playbook --inventory option, or by existance in
the inventory directory.  For runtime management, it must also be copied/symlinked
into the play or role's 'action_plugins' directory as: 'ic_add.py', 'ic_delete.py',
ic_reset.py', and 'ic_update.py'.  It may also be called directly, with the
assumption it's execution environment is identical to future ansible-playbook
commands.  Add/Update input may include a 'join_groups' list, which will be acted upon
but not stored.  Cache file placement via env. var $WORKSPACE or $ARTIFACTS is also
possible (see source).
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type
import argparse
import errno
import json
import os
from contextlib import contextmanager
import fcntl
import sys
import tempfile
from copy import deepcopy
try:
    import yaml
    try:
        from yaml import CLoader as Loader, CDumper as Dumper
    except ImportError:
        from yaml import Loader, Dumper
except ImportError:
    sys.stderr.write("PyYAML / LibYAML import failure, is it installed?\n")
    raise()

from ansible.module_utils.six import iteritems, string_types
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.action import ActionBase
from ansible.utils.vars import isidentifier

USAGE = "\n".join(__doc__.splitlines()[2:])

class InvCache(object):
    """
    Represents a single-source, on-disk cache of Ansible inventory details

    :param cachefile_basedir: Existing directory path where persistent cache
                              file should live.  If None, ``tempfile.gettempdir()``
                              is used.
    :param cachefile_name: Optional, use a specific filename within cachefile_basedir.
    """

    VERSION = 1

    DEFAULT_GROUPS = ('all', 'subjects')  # 'all' is mandatory

    # When non-none, represents the "empty" default contents of newly created cache
    DEFAULT_CACHE = None

    # Private, do not use
    _singleton = None
    _invcache = None
    _filename = None
    _basedir = None


    # Special meta-variables for localhost - undeleteable/unoverwritable.
    RESERVED = ('invcachevers', 'invcachefile')

    def __new__(cls, cachefile_basedir=None, cachefile_name=None):
        if getattr(cls, '_singleton', None) is None:
            if cachefile_basedir:
                cls._basedir = cachefile_basedir
            else:
                # lookup "/tmp" in case elsewhere
                cls._basedir = tempfile.gettempdir()
            if cachefile_name:
                cls._filename = cachefile_name

            DEFAULT_CACHE = dict(_meta=dict(hostvars={}))
            for group in cls.DEFAULT_GROUPS:
                DEFAULT_CACHE[group] = dict(hosts=[], vars={})
            DEFAULT_CACHE['all']['hosts'].append('localhost')
            self = cls._singleton = super(InvCache, cls).__new__(cls)
            self.DEFAULT_CACHE = DEFAULT_CACHE
            # Provide details into Ansible for reference
            hostvars = dict(localhost=dict(invcachefile=self._singleton.filepath,
                                           invcachevers=self.VERSION))
            self.DEFAULT_CACHE['_meta']['hostvars'] = hostvars
        return cls._singleton  # __init__ runs next

    def __init__(self, cachefile_basedir=None, cachefile_name=None):
        del cachefile_basedir,cachefile_name  # consumed by __new__
        with self.locked() as inventory:
            # Validate basic structure
            for group in inventory:
                if group == '_meta':
                    continue
                for crit_sub_key in ('hosts', 'vars'):
                    assert crit_sub_key in inventory[group]
            assert '_meta' in inventory
            assert 'hostvars' in inventory['_meta']
            assert 'localhost' in inventory['_meta']['hostvars']
            for reserved in self.RESERVED:
                assert reserved in inventory['_meta']['hostvars']['localhost']
            # Write cache out to file
            self(inventory)

    def __str__(self):
        return "{0}\n".format(json.dumps(self(), indent=4, separators=(',', ': ')))

    def __call__(self, new_obj=None):
        """
        Replace and/or return current cached JSON object

        :param new_obj: When not None, replaces current cache.
        :returns: Current cache object or dummy
        """
        if new_obj:
            try:
                self.cachefile.seek(0)
                self.cachefile.truncate()
            except IOError:
                pass  # Some file types don't support seek or truncate
            json.dump(new_obj, self.cachefile, indent=2, sort_keys=True)
            self.cachefile.write('\n')  # dump leaves this off :(
            return self()  # N/B: Recursive
        else:
            self.cachefile.seek(0)
            try:
                loaded_cache = json.load(self.cachefile)
            except ValueError as xcpt:  # Could be empty, unparseable, unwritable
                try:
                    loaded_cache = self(deepcopy(self.DEFAULT_CACHE)) # N/B: Recursive
                except RecursionError:
                    raise ValueError("Error loading or parsing default 'empty' cache"
                                     " after writing to disk: {}".format(str(self.DEFAULT_CACHE)))
            return loaded_cache

    @property
    def cachefile(self):
        """Represents the active file backing the cache"""
        if self._invcache and not self._invcache.closed:
            return self._invcache
        # Truncate if new, open for r/w otherwise
        self._invcache = open(self.filepath, 'a+')
        return self._invcache

    @property
    def filepath(self):
        """Represents complete path to on-disk cache file"""
        if self._invcache:  # Might not be open yet
            if hasattr(self._invcache, 'name'):
                return self._invcache.name
            else:
                return str(self._invcache)
        return os.path.join(self._basedir,
                            self.filename)

    @property
    def filename(self):
        """Represents the filename component of the on-disk cache file"""
        if not self._filename:
            # The script always exists inside a sub-directory of a repository or
            # playbook with a meaningful name.  Use that as a distinguishing
            # feature.  More control, comes by way of artifacts_dirpath().
            script_filename = os.path.basename(os.path.realpath(sys.argv[0]))
            script_shortname = script_filename.split('.',1)[0]
            script_dirpath = os.path.dirname(os.path.realpath(sys.argv[0]))
            script_parent_dirpath = os.path.dirname(script_dirpath)
            script_parent_dirname = os.path.basename(script_parent_dirpath)
            # Must be canonical filename for current user and self._basedir for ALL processes
            self._filename = "{}_{}.json".format(script_parent_dirname, script_shortname)
        return self._filename

    @classmethod
    def reset(cls):
        """
        Wipe-out current cache state, including on-disk file
        """
        if cls._singleton and cls._singleton._invcache:
            try:
                cls._singleton._invcache.close()
            except IOError:
                pass
            try:
                os.unlink(cls._singleton.filepath)
            except IOError:
                pass
            cls._singleton._invcache = None
        cls._singleton = None

    @contextmanager
    def locked(self, mode=fcntl.LOCK_EX):
        """
        Context manager protecting returned cache with mode

        :param mode: A value accepted by ``fcntl.flock()``'s ``op`` parameter.
        :returns: Standard Ansible inventory dictionary
        """
        try:
            fcntl.flock(self.cachefile, mode)  # __enter__
            yield self()
        finally:
            fcntl.flock(self.cachefile, fcntl.LOCK_UN) # __exit__

    def gethost(self, hostname):
        """
        Look up details about a host from inventory cache.

        :param hostname: Name of host to retrieve.
        :returns: Tuple containing a dictionary of host variables,
                  and a list of groups.  None if host not
                  found.
        """
        with self.locked(fcntl.LOCK_SH) as inventory:
            groups = []
            hostvars = {}
            for key, value in inventory.items():
                if key == '_meta':
                    hostvars = value.get('hostvars', {}).get(hostname, {})
                else:
                    hosts = value.get("hosts", [])
                    if hostname in hosts:
                        groups.append(key)
            groups = list(set(groups))
        if hostvars != {} or groups != []:
            return (hostvars, groups)
        else:
            return None

    def addhost(self, hostname, hostvars=None, groups=None):
        """
        Add hostname to cache, overwrite hostvars, and all groups.

        :param hostname: An Ansible inventory-hostname (may not be actual hostname).
        :param hostvars: A dictionary of host variables to add, or None
        :param groups: A list of groups for the host to join.
        :returns: Tuple containing a dictionary of host variables, and a list of groups.
        """
        with self.locked(fcntl.LOCK_EX) as inventory:
            self.delhost(hostname, keep_empty=True)
            if hostname != 'localhost':
                if not groups:
                    groups = self.DEFAULT_GROUPS
                if not hostvars:
                    hostvars = {}
            else: # localhost
                if not groups:
                    groups = ["all"]
                if not hostvars:
                    hostvars = {}
                # These must always exist, not be overwritten
                hostvars.update(self.DEFAULT_CACHE['_meta']['hostvars']['localhost'])
            meta = inventory.get("_meta", dict(hostvars=dict()))
            # 'join_groups' treated specially, don't actually add it as a variable
            groups = list(groups) + list(hostvars.pop('join_groups', [])) + ['all']
            # Prune any duplicate groups
            groups = list(set(groups))
            meta["hostvars"][hostname] = hostvars
            for group in groups:
                inv_group = inventory.get(group, dict(hosts=[], vars={}))
                hosts = set(inv_group.get("hosts", []))
                hosts.add(hostname)
                inv_group['hosts'] = list(hosts)
                inventory[group] = inv_group
            # Update and write cache to disk
            self(inventory)
        return hostvars, groups

    def updatehost(self, hostname, hostvars=None, groups=None):
        """
        Update hostname in cache to include hostvars and additional groups.

        :param hostname: An Ansible inventory-hostname (may not be actual hostname).
        :param hostvars: A dictionary of host variables to add/update, or None
        :param groups: A list of new groups for the host to belong.
        :returns: Tuple containing a dictionary of host variables, and a list of groups.
        """
        with self.locked(fcntl.LOCK_EX) as inventory:
            try:
                _hostvars, _groups = self.gethost(hostname)
                if hostvars:
                    _hostvars.update(hostvars)
                if groups:
                    _groups += groups
                return self.addhost(hostname, _hostvars, _groups)
            except TypeError:
                return self.addhost(hostname, hostvars, groups)

    def _dellocalhost(self, inventory):
        hostvars = {}
        groups = []
        for key, value in deepcopy(inventory).items():
            inv_item = inventory[key]
            if key == '_meta':
                meta_hostvars = inv_item['hostvars'].get('localhost', {})
                for _key, _value in deepcopy(meta_hostvars).items():
                    if _key in self.RESERVED:
                        continue
                    hostvars[_key] = _value
                    del inv_item['hostvars']['localhost'][_key]
            elif key == 'all':
                continue
            else:  # non-protected group
                if 'localhost' in value['hosts']:
                    groups.append(key)
                    inv_item['hosts'].remove('localhost')
        return hostvars, groups

    def _delhost(self, inventory, hostname):
        hostvars = {}
        groups = []
        for key, value in deepcopy(inventory).items():
            inv_item = inventory[key]
            if key == '_meta':
                if hostname not in value['hostvars']:
                    continue
                hostvars = deepcopy(inv_item['hostvars'][hostname])
                del inv_item['hostvars'][hostname]
            else:  # Regular group
                if hostname in value['hosts']:
                    groups.append(key)
                    inv_item['hosts'].remove(hostname)
        return hostvars, groups

    def _prunegroups(self, inventory):
        hosts = set()
        for key, value in deepcopy(inventory).items():
            if key == '_meta':
                continue
            if not value['hosts'] and not value['vars'] and key not in self.DEFAULT_GROUPS:
                del inventory[key]
            else:
                hosts |= set(value.get('hosts', []))
        hosts.remove('localhost')
        return len(hosts)

    def delhost(self, hostname, keep_empty=False):
        """
        Remove hostname from inventory, return tuple of host vars. dict and group list

        :param hostname: Ansible hostname to remove from inventory.
        :param keep_empty: If False, remove cache file & reset if no hosts remain in cache.
        :returns: Tuple containing a former dictionary of host variables, and a list of
                  groups or None
        """
        host_count = 0
        with self.locked(fcntl.LOCK_EX) as inventory:
            if hostname == 'localhost':
                hostvars, groups = self._dellocalhost(inventory)
            else:
                hostvars, groups = self._delhost(inventory, hostname)
            host_count = self._prunegroups(inventory)
            # Write out to disk
            self(inventory)
        if not keep_empty and not host_count:
            self.reset()  # removes file
        if hostvars != {} or groups != []:
            return (hostvars, groups)
        else:
            return None

    @staticmethod
    def make_hostvars(host, connection=None, port=None,
                      user=None, priv_key_file=None,
                      passwd=None):
        """Return dictionary of standard/boiler-plate  hostvars"""
        hostvars = dict(ansible_host=str(host))
        if connection:
            hostvars['connection'] = str(connection)
        if port:
            hostvars['port'] = str(port)
        if user:
            hostvars['ansible_user'] = str(user)
        if priv_key_file:
            hostvars['ansible_ssh_private_key_file'] = str(priv_key_file)
        if passwd:
            hostvars['ansible_ssh_pass'] = str(passwd)
        return hostvars

    def str_hostvars(self, hostname):
        hostvars, groups = self.gethost(hostname)
        if hostvars == groups == None:
            raise ValueError("Host '{0}' not found in cache file"
                             " '{1}'".format(hostname, self.cachefile.name))
        del groups  # not used
        return "{0}\n".format(json.dumps(hostvars, indent=4, separators=(',', ': ')))


def _json_yaml(loader, name):
    sys.stderr.write("Reading {0} from standard input, ctrl-d when finished.\n"
                     "".format(name.capitalize()))
    sys.stderr.flush()
    try:
        stdin = sys.stdin.read()
        obj = loader(stdin)
    except ValueError:
        sys.stderr.write("Error parsing stdin:\n{0}\n".format(stdin))
        raise
    if isinstance(obj, list):
        raise ValueError("Expecting dictionary of hostvars, got a list: {0}"
                         "".format(obj))
    try:
        groups = obj.pop("join_groups", [])
        groups = list(set(groups))
    except TypeError:
        groups = None
    return (obj, groups)


def stdin_parse_json():
    """Return hostvars dict and group list tuple, extracted from join_groups key."""
    return _json_yaml(json.loads, 'json')


def stdin_parse_yaml():
    """Return hostvars dict and group list tuple, extracted from join_groups key."""
    yaml_load = lambda _input: yaml.load(_input, Loader=Loader)
    return _json_yaml(yaml_load, 'yaml')


def main(argv=None, environ=None):
    if argv is None:  # Makes unittesting easier
        argv = sys.argv
    if environ is None:
        environ = os.environ  # Side-effects: this isn't a dumb-dictionary

    parser = argparse.ArgumentParser(description="Static inventory cache manipulator,"
                                                 " and dynamic inventory script",
                                     epilog=USAGE)
    parser.add_argument('--debug', action="store_true", default=False,
                        help="Print debugging messages to stderr.")
    # All are mutually exclusive
    group = parser.add_mutually_exclusive_group(required=True)
    # Ansible API
    group.add_argument("--list", action="store_true", default=False,
                       help="Get variables for entire inventory.")
    group.add_argument('--host', default=None, metavar="HOSTNAME",
                       help="Get variables for the host identified by <HOSTNAME>.")
    # InvCache API
    read_vars = "reading variables from stdin"
    group.add_argument('-a', '--add', metavar="HOSTNAME", default=None,
                       help="Add <HOSTNAME> to inventory, {0}.".format(read_vars))
    group.add_argument('-u', '--update', metavar="HOSTNAME", default=None,
                       help="Update or Add <HOSTNAME> to inventory, {0}.".format(read_vars))
    group.add_argument('-d', '--delete', metavar="HOSTNAME", default=None,
                       help="Delete <HOSTNAME> from inventory")
    group.add_argument('-r', '--reset', action="store_true", default=False,
                       help="Reset cache, removing persistent cache file.")
    # InvCache API optional
    parser.add_argument('-f', '--format', choices=('json', 'yaml'), default='json',
                        metavar="FORMAT",
                        help="Use alternate format <FORMAT>, when called"
                             " to --add or --update <HOSTNAME>.  Supported"
                             " formats are 'json' and 'yaml'.")
    parser.add_argument('-c', '--cache', default=None, metavar="FILEPATH",
                        help="Force use of back-end cache file at <FILEPATH>")

    opts = parser.parse_args(args=argv[1:])
    if opts.debug:
        debug = lambda msg: sys.stderr.write("# DEBUG: {}\n".format(msg))
        debug('Debugging enabled\n')
    else:
        debug = lambda msg: None

    # Load / Create cache
    if opts.cache:
        invcache = InvCache(os.path.dirname(opts.cache), os.path.basename(opts.cache))
    else:
        invcache = InvCache(artifacts_dirpath(environ))
    debug('Using cache file: {0}'.format(invcache.filepath))
    do_not_break_ansible = lambda: sys.stdout.write('\n{}\n')
    hostvars_groups = None

    if not opts.host and not opts.list:
        debug("Expecting {0} format input".format(opts.format))
        opts.format = globals()['stdin_parse_{0}'.format(opts.format)]

    if opts.host:  # exclusive of opts.list
        debug("Listing hostvars for {0}".format(opts.host))
        try:
            sys.stdout.write(invcache.str_hostvars(opts.host))
        except TypeError as xcept:
            debug("Host does not exist in cache")
            do_not_break_ansible()
    elif opts.list:
        debug("Listing entire inventory")
        try:
            sys.stdout.write(str(invcache))
        except Exception as xcept:
            debug("Something bad happened: {0}: {1}".format(xcept.__class__.__name__, xcept))
            do_not_break_ansible()
    elif opts.add:
        hostvars, groups = opts.format()
        debug("Adding host {0} to groups {1} with hostvars {2}"
              "".format(opts.add, groups, hostvars))
        hostvars_groups = invcache.addhost(opts.add, hostvars, groups)
    elif opts.update:
        hostvars, groups = opts.format()
        debug("Updating host {0} to groups {1} with hostvars {2}"
              "".format(opts.update, groups, hostvars))
        hostvars_groups = invcache.updatehost(opts.update, hostvars, groups)
    elif opts.delete:
        debug("Deleting host {0}".format(opts.delete))
        hostvars_groups = invcache.delhost(opts.delete, False)  # TODO: keep_empty?
    elif opts.reset:
        debug("Clobbering cache, removing file: {0}".format(invcache.filepath))
        invcache.reset()
    else:
        debug("Not sure what to do")
        do_not_break_ansible()

    # for add/update/delete, show what was done
    if hostvars_groups and opts.debug:
        debug("Changed: {0}".format(hostvars_groups))


def artifacts_dirpath(environ=None):
    """Return complete path to directory where testing artifacts should be stored"""
    if environ is None:
        environ = os.environ  # Side-effects: this isn't a dumb-dictionary

    artifacts = environ.get("ARTIFACTS", '').strip()
    if not artifacts:
        artifacts = '/None'
    workspace = environ.get("WORKSPACE", '').strip()
    if not workspace:
        workspace = '/None'
    tempdir = tempfile.gettempdir().strip()
    try_dirpaths = (artifacts,
                    os.path.join(workspace, "artifacts"),
                    workspace,
                    os.path.join(tempdir, "artifacts"),
                    tempdir)
    for try_dirpath in try_dirpaths:
        if not try_dirpath or '/None' in try_dirpath:
            continue
        try:
            # Fails if leaf-directory exists
            if not os.path.isdir(try_dirpath):
                os.makedirs(try_dirpath)
            # Make sure writing works
            tempfile.TemporaryFile(dir=try_dirpath).close()
            return try_dirpath
        except OSError as xcept:
            continue
    raise OSError("Could not find a writeable directory to use among: {}"
                  "".format(try_dirpaths))


class ActionModule(ActionBase):
    """Manipulate Inventory hosts + facts as a task"""

    TRANSFERS_FILES = False

    @property
    def hostvars(self):
        return self._task._variable_manager.get_vars()['hostvars']

    def _fail(self, result, msg):
        result['msg'] = msg
        result['failed'] = True

    def _get_invcache(self, result):
        # Ensure we use the same cache file as the inventory script
        invcachevers = self.hostvars['localhost'].get('invcachevers', 0)
        if invcachevers == 1:
            try:
                invcachefile = self.hostvars['localhost']['invcachefile']
                result['inventory_cachefile'] = invcachefile
                return InvCache(os.path.dirname(invcachefile), os.path.basename(invcachefile))
            except KeyError:
                self._fail(result, "Invalid version 1 cache, please check the action"
                                   " plugin and dynamic inventory script are identical.")
        if invcachevers == 0:
            self._fail(result, "The invcache action plugin cannot function"
                               " unless it is also present as an inventory script."
                               "\n{0}".format(USAGE))
        else:
            self._fail(result, "Unsupported version of invcache: {0},"
                               " ensure dynamic inventory invcache.py"
                               " exactly matches action plugin (symlink)".format(invcachevers))
        return None

    def _render_args(self, result, task_args):
        new_task_args = {}
        for (k, v) in iteritems(self._task.args):
            k = self._templar.template(k)
            if not isidentifier(k):
                self._fail(result, "The variable name '%s' is not valid for use in ansible." % k)
                return None
            if isinstance(v, string_types) and v.lower() in ('true', 'false', 'yes', 'no'):
                v = boolean(v, strict=False)
            new_task_args[k] = self._templar.template(v)
        return new_task_args

    def _subj_host(self, task_args):
        # Use the executing host unless inventory_hostname is specified
        task_host = self._templar._available_variables['inventory_hostname']
        # 'inventory_hostname' is magic/optional, meta-argument, don't set as a fact
        return task_args.pop('inventory_hostname', task_host)

    def _handle_op(self, result, task_args, invcache, ic_op):
        subj_host = self._subj_host(task_args)
        before_hostvars_groups = invcache.gethost(subj_host)  # tuple or None
        if ic_op in ('add', 'update'):

            # join_groups is a meta-arg, don't set it as fact
            join_groups = task_args.pop('join_groups', [])

            if ic_op == 'add':
                invcache.addhost(subj_host, task_args, join_groups)
            else:
                invcache.updatehost(subj_host, task_args, join_groups)

            hostvars, groups = invcache.gethost(subj_host)
            # Actual mechanism is left up to ansible to handle
            result['add_host'] = dict(host_name=subj_host, groups=groups, host_vars=hostvars)
            result['add_group'] = groups
            if (hostvars, groups) != before_hostvars_groups:
                result['changed'] = True
            else:
                result['changed'] = False
            result['msg'] = ("Static inventory {0} of {1} with vars {2} and joining groups {3}"
                             "".format(ic_op, subj_host, task_args, join_groups))
        elif ic_op == 'delete':
            hostvars_groups = invcache.delhost(subj_host)
            if hostvars_groups is not None:
                result['changed'] = True
                result['msg'] = ("Static inventory deleted {0}, former vars/groups {1}"
                                 "".format(subj_host, hostvars_groups))
            else:
                result['changed'] = False  # Host didn't exist
        elif ic_op == 'reset':
            invcache.reset()
            result['changed'] = True
            result['msg'] = "Static inventory reset"
        else:
            self._fail(result, "Unsupported invcache '{0}' operation".format(ic_op))

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()
        result = super(ActionModule, self).run(tmp, task_vars)

        # One object classifies three operation types (add/update/delete)
        ic_op = result["ic_op"] = self._task.action.split('_', 1)[1]

        # Depending on how task was called, argument keys could also be templates
        task_args = self._render_args(result, self._task.args)
        if task_args is None:
            return result  # error occured

        invcache = self._get_invcache(result)
        if not invcache:
            return result  # something bad happened

        # Needed for "changed" comparison
        self._handle_op(result, task_args, invcache, ic_op)
        return result


if __name__ == '__main__':
    main()
