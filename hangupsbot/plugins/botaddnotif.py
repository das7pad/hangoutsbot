"""
Plugin for monitoring if bot is added to a HO and report it to the bot admins.
Add a "botaddnotif_enable": true  parameter in the config.json file.

Author: @cd334
"""

import hangups

from hangupsbot import plugins


def _initialise():
    plugins.register_sync_handler(_handle_join_notify, "membership_once")


async def _handle_join_notify(bot, event):
    if not event.conv_event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_JOIN:
        return

    admins = bot.config.get_option('admins')

    if event.user_id.chat_id in admins:
        return

    # has bot been added to a new hangout?
    bot_id = bot.user_self()['chat_id']
    if bot_id not in event.conv_event.participant_ids:
        return

    if not bot.config.get_option("botaddnotif_enable"):
        return

    # send message to admins
    for admin_id in admins:
        if admin_id != bot_id:
            await bot.coro_send_to_user(
                admin_id,
                _('<b>{}</b> has added me to hangout <b>{}</b>').format(
                    event.user.full_name, event.conv.name))
