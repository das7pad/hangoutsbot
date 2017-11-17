"""simple cache with timeout and automatic load and dump to memory"""
__author__ = 'das7pad@outlook.com'

import asyncio
import time
import logging
from collections import namedtuple

from hangupsbot import plugins

logger = logging.getLogger(__name__)


CacheItemBase = namedtuple('CacheItemBase',
                           ('value', 'timeout', 'destroy_timeout'))


class CacheItem(CacheItemBase):
    """Lightweight Item for caching

    Args:
        value: any type, object to store
        timeout: int, time in seconds an object should be stored further the
         last access
        destroy_timeout: int, unix timestamp as end of life for the item
    """
    __slots__ = ()
    def __new__(cls, value, timeout, destroy_timeout):
        self = super().__new__(cls, value, timeout, destroy_timeout)
        return self

    def update_timeout(self):
        """increases the destroy timeout with the configured timeout

        Returns:
            a new instance if the timeout should be increased otherwise the old
        """
        if not self.timeout:
            # increase_on_access is set to False, no need to update the timeout
            return self
        return CacheItem(self.value, self.timeout, time.time() + self.timeout)


class Cache(dict):
    """store items for a given timeout which could be extended on access

    Args:
        default_timeout: int, timeout for each item if no other is given, this
            value also sets the intervall for the cleanup
        name: string, a custom identifier for the log entrys
        increase_on_access: boolean, change store behavior, If True an item will
            be stored further the given timeout if one accessed the items value
        dump_config: tuple, (intervall, path)
            intervall: int, time in seconds the cache should be dumped
            path: list of strings, path in memory to the location to dump into
    """
    __slots__ = ('bot', '_name', '_default_timeout', '_increase_on_access',
                 '_dump_config')
    def __init__(self, default_timeout, name=None, increase_on_access=True,
                 dump_config=None):
        super().__init__()
        self._name = name
        self._default_timeout = default_timeout
        self._increase_on_access = increase_on_access
        self._dump_config = dump_config
        self.bot = plugins.tracking.bot

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    def start(self):
        """start the cleanup, restore old entrys and start dumping to memory"""
        plugins.start_asyncio_task(self._periodic_cleanup)

        # loading and dumping depends on a configured intervall and dump path
        if self._dump_config is not None:
            self._load_entrys()
            self.bot.memory.on_reload.add_observer(self._load_entrys)

            plugins.start_asyncio_task(self._periodic_dump)

    def get(self, identifier, pop=False, ignore_timeout=False):
        """receive an entry from cache

        Args:
            identifier: string, unique id for a cache entry
            pop: boolean, toggle to remove the item from cache
            ignore_timeout: boolean, toogle to also get outdated items

        Returns:
            cached entry with no specific type, or the result of .__missing__
            if no entry was found under the given identifier
        """
        item = super().get(identifier)
        if item is None:
            logger.debug('[%s] MISS for %s', self._name, identifier)
            return self.__missing__(identifier)

        if item.destroy_timeout < time.time():
            logger.debug('[%s] OUTDATED-HIT for %s', self._name, identifier)
            if not ignore_timeout:
                self.pop(identifier, None)
                return self.__missing__(identifier)
        else:
            logger.debug('[%s] HIT for %s', self._name, identifier)

        if pop:
            # explicit cleanup
            self.pop(identifier, None)
        else:
            super().__setitem__(identifier, item.update_timeout())
        return item.value

    def add(self, identifier, value, timeout=None, destroy_timeout=None):
        """insert a new entry to the cache or fail gracefully

        Args:
            identifier: string, unique id for the cache entry
            value: any object that should be cached
            timeout: int, custom timeout (sec) for the object to remain in cache
            destroy_timeout: int, a custom timestamp as end of life for the item

        Returns:
            boolean, False if the identifier is not unique, True on success
        """
        if identifier in self:
            return False
        if timeout is None or not isinstance(timeout, int):
            timeout = self._default_timeout

        destroy_timeout = destroy_timeout or time.time() + timeout

        if not self._increase_on_access:
            timeout = 0
        super().__setitem__(identifier,
                            CacheItem(value, timeout, destroy_timeout))
        return True

    ############################################################################
    # PRIVATE METHODS
    ############################################################################

    async def _periodic_cleanup(self, dummy=None):
        """remove old cache entrys, sleep ._default_timeout before each run

        Args:
            dummy: unused
        """
        try:
            while True:
                await asyncio.sleep(self._default_timeout)
                now = time.time()
                for identifier, item in self.copy().items():
                    if item.destroy_timeout < now:
                        self.pop(identifier, None)
        except asyncio.CancelledError:
            return

    def _load_entrys(self):
        """load cache entrys from memory"""
        path = self._dump_config[1]
        self.bot.memory.ensure_path(path)

        for identifier, value in self.bot.memory.get_by_path(path).items():
            self.add(identifier, *value)

    async def _periodic_dump(self, dummy=None):
        """load the last cache state from memory and schedule dumping to memory

        Args:
            dummy: unused
        """
        def _dump(path, only_on_new_itmes=True):
            """export the currently cached items to memory

            Args:
                path: list of string, path in the memory as target for the dump
                only_on_new_itmes: boolean, set to False to dump also if
                 items got removed or timeouts have changed
            """
            mem = self.bot.memory.get_by_path(path)
            dump = self.copy()
            items_mem = set(mem)
            items_dump = set(dump)
            if items_mem == items_dump:
                logger.debug('[%s] matches with ["%s"]',
                             self._name, '"]["'.join(path))
                if only_on_new_itmes:
                    # ignore outdated items
                    return
            else:
                logger.debug('[%s@"%s"] changed: %s -> %s entrys',
                             self._name, '"]["'.join(path), len(mem), len(dump))
                if not items_dump - items_mem and only_on_new_itmes:
                    # ignore removed items
                    return

            self.bot.memory.set_by_path(path, dump)
            self.bot.memory.save()

        intervall, path = self._dump_config
        try:
            while True:
                await asyncio.sleep(intervall)
                _dump(path)
        except asyncio.CancelledError:
            logger.info('flushing [%s]', self._name)
            _dump(path, only_on_new_itmes=False)

    def __del__(self):
        """explicit cleanup"""
        self.bot.memory.on_reload.remove_observer(self._load_entrys)

    def __missing__(self, identifier):
        """may be overwritten"""
        return None

    def __getitem__(self, identifier):
        return self.get(identifier)

    def __setitem__(self, identifier, value):
        return self.add(identifier, value)

    def __delitem__(self, identifier):
        self.pop(identifier, None)
