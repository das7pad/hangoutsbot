"""Apply the rate limit per channel to the sending queue"""

import asyncio

from hangupsbot.sync.sending_queue import (
    AsyncQueue,
    QueueCache,
)


class SlackMessageQueue(AsyncQueue):
    __slots__ = (
        '_next_message',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_message = 0

    async def _send(self, args, kwargs):
        """This method is called sequentially"""
        now = self._loop.time()

        if self._next_message > now:
            await asyncio.sleep(self._next_message - now)

        try:
            await super()._send(args, kwargs)
        finally:
            self._next_message = self._loop.time() + 1


class SlackMessageQueueCache(QueueCache):
    __slots__ = ()
    _queue = SlackMessageQueue
