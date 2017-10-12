"""
Identify images, upload them to google plus, post in hangouts
"""
import logging

import plugins
from plugins.image import image_validate_and_upload_single


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_sync_handler(_watch_image_link, "message_once")


async def _watch_image_link(bot, event):
    # Don't handle events caused by the bot himself
    if event.user.is_self:
        return

    text = event.text

    if text.startswith(('https://', 'http://', '//')):
        image_id = await image_validate_and_upload_single(text)

        if image_id:
            await bot.coro_send_message(event.conv.id_, None, image_id=image_id)
