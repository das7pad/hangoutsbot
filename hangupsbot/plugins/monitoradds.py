"""
Plugin for monitoring new adds to HOs and alerting if users were not added by an admin or mod.
Add mods to the config.json file either globally or on an individual HO basis.
Add a "watch_new_adds": true  parameter to individual HOs in the config.json file.

Author: @Riptides
"""
import logging

import hangups

import plugins


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_sync_handler(_watch_new_adds, "membership_once")
    plugins.register_admin_command(["addmod", "delmod"])


async def _watch_new_adds(bot, event):
    # Check if watching for new adds is enabled
    if not bot.get_config_suboption(event.conv_id, 'watch_new_adds'):
        return

    # JOIN
    if event.conv_event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_JOIN:
        # Check if the user who added people is a mod or admin
        admins_list = bot.get_config_suboption(event.conv_id, 'admins')
        if event.user_id.chat_id in admins_list:
            return

        config_mods = bot.get_config_suboption(event.conv_id, 'mods') or []
        tagged_mods = list(bot.tags.userlist(event.conv_id, "mod").keys())
        tagged_botkeeper = list(bot.tags.userlist(event.conv_id, "botkeeper").keys())

        mods_list = config_mods + tagged_mods + tagged_botkeeper
        try:
            if event.user_id.chat_id in mods_list:
                return
        except TypeError:
            # The mods are likely not configured. Continuing...
            pass

        # Generate list of added or removed users
        event_users = [event.conv.get_user(user_id) for user_id
                       in event.conv_event.participant_ids]
        names = ', '.join([user.full_name for user in event_users])

        html = _("<b>!!! WARNING !!!</b>\n"
                 "\n"
                 "<b>{0}</b> invited <b>{1}</b> without authorization.\n"
                 "\n"
                 "<b>{1}</b>: Please leave this hangout and ask a moderator to add you. "
                 "Thank you for your understanding.").format(event.user.full_name, names)

        await bot.coro_send_message(event.conv, html)

def addmod(bot, event, *args):
    """add user id(s) to the whitelist of who can add to a hangout"""
    mod_ids = list(args)
    if bot.get_config_suboption(event.conv_id, 'mods') is not None:
        for mod in bot.get_config_suboption(event.conv_id, 'mods'):
            mod_ids.append(mod)
        bot.config.set_by_path(["mods"], mod_ids)
        bot.config.save()
        html_message = _("<i>Moderators updated: {} added</i>")
        return html_message.format(args[0])

    bot.config.set_by_path(["mods"], mod_ids)
    bot.config.save()
    html_message = _("<i>Moderators updated: {} added</i>")
    return html_message.format(args[0])

def delmod(bot, dummy, *args):
    """remove user id(s) from the whitelist of who can add to a hangout"""
    if not bot.config.get_option('mods'):
        return

    mods = bot.config.get_option('mods')
    mods_new = []
    for mod in mods:
        if args[0] != mod:
            mods_new.append(mod)

    bot.config.set_by_path(["mods"], mods_new)
    bot.config.save()
    html_message = _("<i>Moderators updated: {} removed</i>")
    return html_message.format(args[0])
