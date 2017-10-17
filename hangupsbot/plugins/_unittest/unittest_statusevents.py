import datetime
import logging

import hangups

from hangupsbot import plugins


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_handler(on_watermark_update, "watermark")
    plugins.register_handler(on_typing_notification, "typing")


def on_typing_notification(bot, event):
    if event.from_bot:
        # ignore self events
        return

    typing_status = event.conv_event.status

    user_chat_id = event.user_id.chat_id
    user_full_name = event.user.full_name
    conv_title = bot.conversations.get_name(event.conv_id,
                                            "? {}".format(event.conv_id))

    if typing_status == hangups.TYPING_TYPE_STARTED:
        logger.info("%s (%s) typing on %s (%s)",
                    user_full_name, user_chat_id, conv_title, event.conv_id)

    elif typing_status == hangups.TYPING_TYPE_PAUSED:
        logger.info("%s (%s) paused typing on %s (%s)",
                    user_full_name, user_chat_id, conv_title, event.conv_id)

    elif typing_status == hangups.TYPING_TYPE_STOPPED:
        logger.info("%s (%s) stopped typing on %s (%s)",
                    user_full_name, user_chat_id, conv_title, event.conv_id)

    else:
        raise ValueError("unknown typing status: %s" % typing_status)


def on_watermark_update(bot, event):
    if event.from_bot:
        # ignore self events
        return

    utc_datetime = datetime.datetime.fromtimestamp(
        event.timestamp // 1000000, datetime.timezone.utc
    ).replace(microsecond=(event.timestamp % 1000000))

    logger.info("%s (%s) read up to %s (%s) on %s (%s)",
                event.user.full_name,
                event.user_id.chat_id,
                utc_datetime,
                event.timestamp,
                bot.conversations.get_name(event.conv_id,
                                           "? {}".format(event.conv_id)),
                event.conv_id)
