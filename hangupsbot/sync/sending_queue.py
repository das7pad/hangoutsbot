"""keep the sequence for async tasks"""
__author__ = 'das7pad@outlook.com'

import asyncio
import functools
import logging

from utils.cache import Cache

logger = logging.getLogger(__name__)

SENDING_BLOCK_RETRY_DELAY = 5   # seconds

class Queue(list):
    """a queue to schedule synced calls and remain the sequence in processing

    Args:
        group: string, identifier for a platform
        func: callable, will be called with the scheduled args/kwargs
    """
    __slots__ = ('_logger', '_func', '_group', '_lock')
    _loop = asyncio.get_event_loop()
    _blocks = {'__global__': False}
    _pending_tasks = {}

    def __init__(self, group, func=None):
        super().__init__()
        self._logger = logging.getLogger('%s.%s' % (__name__, group))
        self._func = func
        self._group = group
        self._lock = asyncio.Lock(loop=self._loop)

        # do not overwrite an active block
        self._blocks.setdefault(group, False)
        # do not reset the counter
        self._pending_tasks.setdefault(group, 0)

    @property
    def _blocked(self):
        """check for a global or local sending block

        Returns:
            True if any block got applied otherwise False
        """
        return self.__block['__global__'] or self.__block[self._group]

    @property
    def _running(self):
        """check if a queue processor is already running

        Returns:
            boolean, True if a queue processor is running, otherwise False
        """
        return self._lock.locked()

    def schedule(self, *args, **kwargs):
        """queue an item with the given args/kwargs for the coro"""
        self._pending_tasks[self._group] += 1
        self.append((self._blocked, args, kwargs))
        asyncio.ensure_future(self._process(), loop=self._loop)

    async def local_stop(self, timeout):
        """apply a submit-block to all group members and wait for pending tasks

        stop a group without a reference to an instance of a group member:
        Queue(group).local_stop()

        Args:
            timeout: int, time in seconds to wait for pending tasks to complete
        """
        self._blocks[self._group] = True
        if self._pending_tasks[self._group] > 0:
            self._logger.info('waiting for %s tasks',
                              self._pending_tasks[self._group])
        while timeout > 0:
            if self._pending_tasks[self._group] <= 0:
                break
            timeout -= 0.1
            await asyncio.sleep(0.1)
        else:
            self._logger.warning('%s task%s did not finished',
                                 self._pending_tasks[self._group],
                                 ('s' if self._pending_tasks[self._group] > 1
                                  else ''))

    @classmethod
    async def global_stop(cls, timeout):
        """apply a submit-block to all queues and wait for pending tasks

        Args:
            timeout: int, time in seconds to wait for pending tasks to complete
        """
        cls._blocks['__global__'] = True
        pending = {group: tasks
                   for group, tasks in cls._pending_tasks.items()
                   if tasks > 0}
        if not pending:
            return

        logger.info('global stop: waiting for %s tasks',
                    sum(pending.values()))
        await asyncio.gather(*[Queue(group, None).local_stop(timeout)
                               for group in pending])

    @classmethod
    def release_block(cls, group=None):
        """unset a sending block

        Args:
            group: string, platform identifier or None to release globally
        """
        if group is None:
            cls._blocks.clear()
            cls._blocks['__global__'] = False
            cls._pending_tasks.clear()
        else:
            cls._blocks[group] = False
            cls._pending_tasks[group] = 0

    async def _process(self):
        """process the queue and await the result on each call"""
        if not self:
            # all tasks are handled
            return

        if self._running:
            # only one queue processor is allowed
            return

        async with self._lock:
            try:
                blocked, args, kwargs = self.pop(0)
                if blocked:
                    delay = 0
                    while delay < SENDING_BLOCK_RETRY_DELAY:
                        if not self._blocked:
                            # block got released
                            break
                        await asyncio.sleep(.1)
                        delay += .1
                    else:
                        self._logger.error(
                            'block timeout reached\ndiscard args=%s, kwargs=%s',
                            repr(args), repr(kwargs))
                        return

                self._logger.debug('sending %s %s', repr(args), repr(kwargs))
                await self._send(args, kwargs)
                self._logger.debug('sent %s %s', repr(args), repr(kwargs))
            finally:
                self._pending_tasks[self._group] -= 1
                asyncio.ensure_future(self._process(), loop=self._loop)

    async def _send(self, args, kwargs):
        """perform the sending of the scheduled content

        Args:
            args: tuple, positional arguments for the coro
            kwargs: dict, keyword arguments for the coro
        """
        wrapped = functools.partial(self._func, *args, **kwargs)
        try:
            await asyncio.shield(self._loop.run_in_executor(None, wrapped))
        except asyncio.CancelledError:
            pass
        except Exception as err:                  # pylint: disable=broad-except
            self._logger.warning('sending args="%s", kwargs="%s" failed:\n%s',
                                 args, kwargs, repr(err))


class AsyncQueue(Queue):
    """a queue to schedule async calls and remain the sequence in processing

    Args:
        group: string, identifier for a platform
        func: coroutine function, will be called with the scheduled args/kwargs
    """
    __slots__ = ()

    async def _send(self, args, kwargs):
        """perform the sending of the scheduled content

        Args:
            args: tuple, positional arguments for the coro
            kwargs: dict, keyword arguments for the coro
        """
        try:
            await asyncio.shield(self._func(*args, **kwargs))
        except asyncio.CancelledError:
            pass
        except Exception as err:                  # pylint: disable=broad-except
            self._logger.warning('sending args="%s", kwargs="%s" failed:\n%s',
                                 args, kwargs, repr(err))


class QueueCache(Cache):
    """caches Queues and recreates one if a cache miss happens

    Args:
        timeout: integer, time in seconds for a queue to live in cache
        group: string, identifier for a platform to separate queues for
        func: coroutine function, will be called with the scheduled args/kwargs
    """
    __slots__ = ('_default_args',)
    _queue = Queue

    def __init__(self, timeout, group, func):
        super().__init__(timeout, name='Sending Queues@%s' % group)
        self._default_args = (group, func)
        self._queue.release_block(group)

    def __missing__(self, identifier):
        queue = self._queue(*self._default_args)
        self.add(identifier, queue)
        return queue

    def get(self, identifier):
        """get the message queue of a chat

        Args:
            identifier: string, conversation id

        Returns:
            an instance of ._queue, AsyncQueue or Queue
        """
        #pylint:disable=arguments-differ
        return super().get(identifier, ignore_timeout=True)


class AsyncQueueCache(QueueCache):
    """caches AsyncQueues and recreates one if a cache miss happens

    Args:
        timeout: integer, time in seconds for a queue to live in cache
        group: string, identifier for a platform to separate queues for
        func: coroutine function, will be called with the scheduled args/kwargs
    """
    __slots__ = ()
    _queue = AsyncQueue
