#!/usr/bin/env python3

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

class InvCache(object):
    """
    Represents a single-source, on-disk cache of Ansible inventory details

    :param cachefile_basedir: Existing directory path where persistent cache
                              file should live.  If None, ``tempfile.gettempdir()``
                              is used.
    """

    VERSION = "1.0"

    DEFAULT_GROUPS = ('all', 'subjects')  # 'all' is mandatory

    # When non-none, represents the "empty" default contents of newly created cache
    DEFAULT_CACHE = None

    # When non-none, contains the base-directory for the persistent cache file
    basedir = None

    # Private, do not use
    _singleton = None
    _invcache = None

    def __new__(cls, cachefile_basedir=None):
        if getattr(cls, '_singleton', None) is None:
            cls.DEFAULT_CACHE = dict(_meta=dict(hostvars={}))
            for group in cls.DEFAULT_GROUPS:
                cls.DEFAULT_CACHE[group] = dict(hosts=[], vars={})
            if cachefile_basedir:
                cls.basedir = cachefile_basedir
            else:
                # lookup "/tmp" in case elsewhere
                cls.basedir = tempfile.gettempdir()
            cls._singleton = super(InvCache, cls).__new__(cls)
            # Provide details into Ansible for possible convenience
            cls.DEFAULT_CACHE['all']['hosts'].append('localhost')
            hostvars = dict(localhost=dict(invcachefile=cls._singleton.filepath,
                                           invcachevers=cls.VERSION))
            cls.DEFAULT_CACHE['_meta']['hostvars'] = hostvars
        return cls._singleton  # __init__ runs next

    def __init__(self, cachefile_basedir=None):
        del cachefile_basedir  # consumed by __new__
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
            assert 'invcachefile' in inventory['_meta']['hostvars']['localhost']
            assert 'invcachevers' in inventory['_meta']['hostvars']['localhost']
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
            return self()  # N/B: Recursive
        else:
            self.cachefile.seek(0)
            try:
                output_json = json.load(self.cachefile)
            except ValueError as xcpt:  # Could be empty, unparseable, unwritable
                try:
                    return self(deepcopy(self.DEFAULT_CACHE)) # N/B: Recursive
                except RecursionError:
                    raise ValueError("Error loading or parsing default 'empty' cache"
                                     " after writing to disk: {}".format(str(self.DEFAULT_CACHE)))
            return output_json

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
        return os.path.join(self.basedir,
                            self.filename)

    @property
    def filename(self):
        """Represents the filename component of the on-disk cache file"""
        # The script always exists inside a sub-directory of a repository or
        # playbook with a meaningful name.  Use that as a distinguishing
        # feature.  More control, comes by way of artifacts_dirpath().
        script_filename = os.path.basename(os.path.realpath(sys.argv[0]))
        script_shortname = script_filename.split('.',1)[0]

        script_dirpath = os.path.dirname(os.path.realpath(sys.argv[0]))
        script_parent_dirpath = os.path.dirname(script_dirpath)
        script_parent_dirname = os.path.basename(script_parent_dirpath)
        # Must be canonical filename for current user and self.basedir for ALL processes
        return "{}_{}.json".format(script_parent_dirname, script_shortname)

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
        Update cache, add/overwrite hostname with hostvars to specified groups.

        :param hostname: An Ansible inventory-hostname (may not be actual hostname).
        :param hostvars: A dictionary of host variables to add, or None
        :param groups: A list of groups for the host to join.
        :returns: Tuple containing a dictionary of host variables, and a list of groups.
        """
        if not groups:
            if hostname != 'localhost':
                groups = self.DEFAULT_GROUPS
            else:
                groups = ["all"]
        if not hostvars:
            hostvars = {}
        with self.locked(fcntl.LOCK_EX) as inventory:
            meta = inventory.get("_meta", dict(hostvars=dict()))
            if hostname == 'localhost':
                for unreserved in set(hostvars) - set(('invcachefile', 'invcachevers')):
                    del hostvars[unreserved]
            meta["hostvars"][hostname] = hostvars
            for group in list(set(groups)):
                inv_group = inventory.get(group, dict(hosts=[], vars={}))
                hosts = inv_group.get("hosts", [])
                _vars = inv_group.get("vars", {})
                hosts.append(hostname)
                hosts = list(set(inv_group["hosts"]))
                inventory[group] = inv_group
            # Update and write cache to disk
            self(inventory)
        return hostvars, groups

    def updatehost(self, hostname, hostvars=None, groups=None):
        """
        Update cache, add/update hostname with hostvars to specified groups.

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
            if key is '_meta':
                for _key, _value in inv_item['hostvars']['localhost'].items():
                    if _key in ('invcachefile', 'invcachevers'):
                        continue
                    hostvars[_key] = _value
                    del inv_item['hostvars']['localhost'][key]
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
        host_count = 0
        for key, value in deepcopy(inventory).items():
            if key == '_meta' or key in self.DEFAULT_GROUPS:
                continue
            if not value['hosts'] and not value['vars']:
                del inventory[key]
            else:
                host_count += len(value['hosts'])
        return host_count

    def delhost(self, hostname, keep_empty=False):
        """
        Remove hostname from inventory, return tuple of host vars. dict and group list

        :param hostname: Ansible hostname to remove from inventory.
        :param keep_empty: If False, remove cache file & reset if no hosts remain in cache.
        :returns: Tuple containing a former dictionary of host variables, and a list of
                  groups or None
        """
        host_count = -1
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
    obj = loader(sys.stdin.read())
    if isinstance(obj, list):
        raise ValueError("Expecting dictionary of hostvars, got a list: {0}"
                         "".format(obj))
    try:
        groups = obj["join_groups"]
        groups = list(set(groups))
        del obj["join_groups"]
    except KeyError:
        groups = []
    return (obj, groups)


def stdin_parse_json():
    """Return hostvars dict and group list tuple, extracted from join_groups key."""
    return _json_yaml(json.loads, 'json')


def stdin_parse_yaml():
    yaml_load = lambda _input: yaml.load(_input, Loader=Loader)
    return _json_yaml(yaml_load, 'yaml')


def main(argv=None, environ=None):
    if argv is None:  # Makes unittesting easier
        argv = sys.argv
    if environ is None:
        environ = os.environ  # Side-effects: this isn't a dumb-dictionary

    parser = argparse.ArgumentParser(description="Static inventory cache manipulator,"
                                                 " and dynamic inventory script",
                                     epilog="Add/Update input may include a"
                                            " 'join_groups' list, which will be"
                                            " acted upon, but otherwise treated as meta-data"
                                            " ( not an actual variable).")
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
    parser.add_argument('-i', '--input', choices=('json', 'yaml'), default='json',
                        metavar="FORMAT",
                        help="Use alternate format <FORMAT>, when {0}"
                             " for --add or --update <HOSTNAME>.")

    opts = parser.parse_args(args=argv[1:])
    if opts.debug:
        debug = lambda msg: sys.stderr.write("# DEBUG: {}\n".format(msg))
        debug('Debugging enabled\n')
    else:
        debug = lambda msg: None

    # Load / Create cache
    invcache = InvCache(artifacts_dirpath(environ))
    debug('Using cache file: {0}'.format(invcache.filepath))
    do_not_break_ansible = lambda: sys.stdout.write('\n{}\n')

    if not opts.host and not opts.list:
        debug("Expecting {0} format input".format(opts.input))
        opts.input = globals()['stdin_parse_{0}'.format(opts.input)]

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
        hostvars, groups = opts.input()
        debug("Adding host {0} to groups {1} with hostvars {2}"
              "".format(opts.add, groups, hostvars))
        invcache.addhost(opts.add, hostvars, groups)
    elif opts.update:
        hostvars, groups = opts.input()
        debug("Updating host {0} to groups {1} with hostvars {2}"
              "".format(opts.update, groups, hostvars))
        invcache.updatehost(opts.update, hostvars, groups)
    elif opts.delete:
        debug("Deleting host {0}".format(opts.delete))
        invcache.delhost(opts.delete, False)  # TODO: keep_empty?
    elif opts.reset:
        debug("Clobbering cache, removing file: {0}".format(invcache.filepath))
        invcache.reset()
    else:
        debug("Not sure what to do")
        do_not_break_ansible()


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
            os.makedirs(try_dirpath, exist_ok=True)
            tempfile.TemporaryFile(dir=try_dirpath).close()
            return try_dirpath
        except OSError:
            continue
    raise OSError("Could not find a writeable directory to use among: {}"
                  "".format(try_dirpaths))


if __name__ == '__main__':
    main()
