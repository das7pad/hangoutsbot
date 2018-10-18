"""cache for a json file with shortcuts to access data"""

import asyncio
import collections
import functools
import glob
import io
import json
import logging
import operator
import os
import shutil
import sys
import time
import traceback
from datetime import datetime

import hangups.event


class Config(collections.MutableMapping):
    """Configuration JSON storage class

    Args:
        path (str): file path of the config file
        failsafe_backups (int): amount of backups that should be kept
        save_delay (int): time in second a dump should be delayed
        name (str): custom name for the logger and reload event
    """
    default = None

    def __init__(self, path, failsafe_backups=0, save_delay=0, name=__name__):
        self.filename = path
        self.config = {}
        self.defaults = {}
        self.failsafe_backups = failsafe_backups
        self.save_delay = save_delay
        self._last_dump = None
        self._timer_save = None
        self.on_reload = hangups.event.Event('%s reload' % name)
        self.logger = logging.getLogger(name)

    @property
    def _changed(self):
        """return whether the config changed since the last dump

        Returns:
            bool: True if config matches with the last dump, otherwise False
        """
        try:
            current_state = json.dumps(self.config, indent=2, sort_keys=True)
        except TypeError:
            # corrupt config
            return True
        return current_state != self._last_dump

    def _make_failsafe_backup(self):
        """remove old backup files above the limit and create a new backup

        the limit refers to the number of .failsafe_backups

        Returns:
            bool: True on a successful new backup, otherwise False
        """
        try:
            with open(self.filename) as file:
                json.load(file)
        except IOError:
            return False
        except ValueError:
            self.logger.warning("%s is corrupted, aborting backup",
                                self.filename)
            return False

        existing = sorted(glob.glob(self.filename + ".*.bak"))
        while len(existing) > (self.failsafe_backups - 1):
            path = existing.pop(0)
            try:
                os.remove(path)
            except IOError:
                self.logger.warning('Failed to remove %s, check permissions',
                                    path)

        backup_file = "%s.%s.bak" % (self.filename,
                                     datetime.now().strftime("%Y%m%d%H%M%S"))
        shutil.copy2(self.filename, backup_file)
        return True

    def _recover_from_failsafe(self):
        """restore data from a recent backup

        Returns:
            bool: True if any backup could be loaded, False if None is
                available or all backups are corrupt or no readable
        """
        existing = sorted(glob.glob(self.filename + ".*.bak"))
        recovery_filename = None
        while existing:
            try:
                recovery_filename = existing.pop()
                with open(recovery_filename, 'r') as file:
                    data = file.read()
                self._update_deep(data)
            except IOError:
                self.logger.warning('Failed to remove %s, check permissions',
                                    recovery_filename)
            except ValueError:
                self.logger.warning("corrupted recovery: %s", self.filename)
            else:
                self.save(delay=False)
                self.logger.warning(
                    "recovered %s successful from %s",
                    self.filename, recovery_filename
                )
                return True
        return False

    def load(self):
        """Load config from file

        Raises:
            OSError: the existing config is not readable or no new config can
                be saved to the configured path
            ValueError: the config file is not a valid json and no backups are
                available
        """
        try:
            with open(self.filename) as file:
                data = file.read()
            self._update_deep(data)
        except IOError:
            if not os.path.isfile(self.filename):
                self.config = {}
                self.save(delay=False)
                return
            raise
        except ValueError:
            if self.failsafe_backups and self._recover_from_failsafe():
                return
            raise
        else:
            self._last_dump = data
            self.logger.info("%s read", self.filename)

    def _update_deep(self, json_str):
        """Update the config from a JSON string

        By replacing the immutable and changed entries only we do not need to
        update all external references.

        Limitations:
            - mutable objects living inside lists can not be updated and are
                replaced instead.

        Args:
            json_str (str): a json formatted string that overrides the config

        Raises:
            ValueError: the string is not a valid json representing of a dict
        """

        def _deep_replace(old, new):
            """replace the content but keep the old data structure

            Assume that the `old` dict and the `new` dict have almost exactly
            the same structure. The `new` dict stores the new values for the
            config and we got external references pointing to mutable objects
            which are living inside the `old` dict.

            Args:
                old (dict): object that is living inside the current config
                new (dict): object with possibly more, fewer or changed entries
            """
            old_keys = set(old)
            new_keys = set(new)

            # discard deleted entries
            for key in old_keys - new_keys:
                old.pop(key)

            # insert new entries
            for key in new_keys - old_keys:
                old[key] = new[key]

            # update existing entries
            for key in old_keys & new_keys:
                old_value = old[key]
                new_value = new[key]

                if not isinstance(old_value, type(new_value)):
                    # overwrite in case of a changed type
                    old[key] = new_value
                    continue

                if isinstance(old_value, dict):
                    # compare recursive
                    _deep_replace(old_value, new_value)
                elif isinstance(old_value, list):
                    # keep the old list object in the config, swap the content
                    old_value.clear()
                    old_value.extend(new_value)
                else:
                    # overwrite in case of an immutable object
                    old[key] = new_value

        _deep_replace(self.config, json.loads(json_str))
        asyncio.ensure_future(self.on_reload.fire())

    def save(self, delay=True, stack=None):
        """dump the cached data to file

        Args:
            delay (bool): set to False to force an immediate dump
            stack (str): stack of the `save` call

        Raises:
            IOError: the config can not be saved to the configured path
        """
        if self._timer_save is not None:
            self._timer_save.cancel()

        if not self._changed:
            # skip dumping as the file is already up to date
            return

        if stack is None:
            frame = sys._getframe().f_back  # pylint:disable=protected-access
            with io.StringIO() as writer:
                traceback.print_stack(frame, file=writer)
                stack = writer.getvalue()

        if self.save_delay and delay:
            self._timer_save = asyncio.get_event_loop().call_later(
                self.save_delay, self.save, False, stack)
            return

        start_time = time.time()

        if self.failsafe_backups:
            self._make_failsafe_backup()

        try:
            self._last_dump = json.dumps(self.config, indent=2, sort_keys=True)
        except TypeError:
            self.logger.error('bad value stored by\n%s', stack)
            self._recover_from_failsafe()
        else:
            with open(self.filename, 'w') as file:
                file.write(self._last_dump)

        interval = time.time() - start_time
        self.logger.info("%s write %s", self.filename, interval)

    def flush(self):
        """force an immediate dump to file"""
        self.logger.info("flushing %s", self.filename)
        self.save(delay=False)

    def get_by_path(self, keys_list, fallback=True):
        """Get an item from .config by path

        Args:
            keys_list (list[str]): describing the path to the value
            fallback (bool): use the default values as fallback for missing
                entries

        Returns:
            mixed: the requested value

        Raises:
            KeyError: the path does not exist
            ValueError: the path does not exist
        """
        try:
            return self._get_by_path(self.config, keys_list)
        except (KeyError, ValueError):
            if not fallback:
                raise
        try:
            return self._get_by_path(self.defaults, keys_list)
        except (KeyError, ValueError):
            raise KeyError('%s has no path %s and there is no default set' %
                           (self.logger.name, keys_list))

    def set_by_path(self, keys_list, value, create_path=True):
        """set an item in .config by path

        Args:
            keys_list (list[str]): describing the path to the value
            value (mixed): the new value
            create_path (bool): toggle to ensure an existing path

        Raises:
            KeyError, ValueError: the path does not exist
        """
        if create_path:
            self.ensure_path(keys_list)
        self.get_by_path(keys_list[:-1],
                         fallback=False)[keys_list[-1]] = value

    def pop_by_path(self, keys_list):
        """remove an item in .config found with the given path

        Args:
            keys_list (list[str]): describing the path to the value

        Returns:
            mixed: the removed value

        Raises:
            KeyError, ValueError: the path does not exist
        """
        return self.get_by_path(keys_list[:-1], False).pop(keys_list[-1])

    @staticmethod
    def _get_by_path(source, path):
        """Get an item from source by path

        Args:
            source (dict): `.config` or `.defaults`
            path (list[str]): describing the path to the value

        Returns:
            mixed: the requested value

        Raises:
            KeyError: the path does not exist
            ValueError: the path does not exist
        """
        if not path:
            return source
        return functools.reduce(operator.getitem, path[:-1], source)[path[-1]]

    def get_option(self, keyname):
        """get a top level entry from config or a default value

        Args:
            keyname (str): top level key

        Returns:
            mixed: the requested value or .default if the key does not exist
        """
        try:
            return self.get_by_path([keyname])
        except KeyError:
            return self.default

    def get_suboption(self, grouping, groupname, keyname):
        """get a third level entry from config with a fallback to top level

        Args:
            grouping (str): top level entry in .config
            groupname (str): second level entry, key in grouping
            keyname (str): third level key as target and also the top level
                key as fallback for a missing key in the path

        Returns:
            mixed: the requested value, it's fallback on top level or
                .default if the key does not exist on both level
        """
        try:
            return self.get_by_path([grouping, groupname, keyname])
        except KeyError:
            return self.get_option(keyname)

    def exists(self, keys_list, fallback=False):
        """check if a path exists in the dict

        Args:
            keys_list (list[str]): describing the path
            fallback (bool): use the default values as fallback for missing
                entries

        Returns:
            bool: True if the full path is resolvable, otherwise False
        """
        try:
            self.get_by_path(keys_list, fallback)
        except (KeyError, TypeError):
            return False
        else:
            return True

    def ensure_path(self, path, base=None):
        """create a path of dicts if the given path does not exist

        Args:
            path (list[str]): describing the path
            base (dict): the source to create the path in

        Returns:
            bool: True if the path did not existed before, otherwise False

        Raises:
            AttributeError: on attempting to override a key pointing to an entry
                in config that is not a dict
        """
        if base is None:
            base = self.config
        try:
            self._get_by_path(base, path)
        except (KeyError, TypeError):
            # the path does not exist
            pass
        else:
            # the path exists, no need to create it again
            return False

        last_key = None
        try:
            for level in path:
                base = base.setdefault(level, {})
                last_key = level
        except AttributeError:
            raise AttributeError('%s has no dict at "%s" in the path %s' %
                                 (self.logger.name, last_key, path)) from None
        return True

    def set_defaults(self, source, path=None):
        """ensure that the dict, path points to, has the structure of the source

        also override to defaults if the type of an entry does not match

        Args:
            source (dict): structure with values
            path (list[str]): path of the target for the defaults in the config

        Raises:
            ValueError: the path could not be created as it would override an
                entry that is not a dict
            AttributeError: a value in source does not match with the type that
                is already in the defaults
        """
        if path is None:
            path = []
        else:
            self.ensure_path(path, base=self.defaults)
        defaults = self._get_by_path(self.defaults, path)
        for key, value in source.items():
            if key not in defaults:
                defaults[key] = value

            elif isinstance(value, dict):
                self.set_defaults(value, path + [key])

            elif isinstance(value, list):
                defaults[key].extend(value)
            else:
                defaults[key] = value

    def validate(self, source, path=None):
        """ensure that the entries in source are all available in the config

        Args:
            source (dict): default dict structure with values
            path (list[str]): list of keys to the dict to validate

        Raises:
            ValueError: the path could not be created as it would override an
                entry that is not a dict
        """
        if path is None:
            path = []
        for key, value in source.items():
            if not self.exists(path + [key]):
                self.set_by_path(path + [key], value)

            elif not isinstance(self.get_by_path(path + [key]), type(value)):
                self.set_by_path(path + [key], value)

            elif isinstance(value, dict) and value:
                self.validate(value, path + [key])

    def __getitem__(self, key):
        return self.get_option(key)

    def __setitem__(self, key, value):
        self.config[key] = value

    def __delitem__(self, key):
        del self.config[key]

    def __iter__(self):
        return iter(self.config)

    def __len__(self):
        return len(self.config)

    def force_taint(self):
        """[DEPRECATED] toggle the changed state to True"""
        self.logger.warning(('[DEPRECATED] .force_taint is no more needed to '
                             'mark the config for a needed dump.'),
                            stack_info=True)
