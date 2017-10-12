"""Allows the user to configure the bot to watch for hangout renames
and change the name back to a default name accordingly"""

import logging

from hangupsbot import plugins
from hangupsbot.commands import command


logger = logging.getLogger(__name__)

HELP = {
    'topic': _('locks a conversation title.\n'
               ' {bot_cmd} topic <new_name>'
               'example: {bot_cmd} topic Alerts'
               'To clear and unlock the title run\n'
               ' {bot_cmd} topic'),
}

def _initialise():
    plugins.register_handler(_watch_rename, "rename")
    plugins.register_admin_command(["topic"])
    plugins.register_help(HELP)


async def _watch_rename(bot, event):

    memory_topic_path = ["conv_data", event.conv_id, "topic"]

    old_name = None
    if bot.memory.exists(memory_topic_path):
        old_name = bot.memory.get_by_path(memory_topic_path)

    if old_name:
        # seems to be a valid topic set for the current conversation

        authorised_topic_change = False

        if not authorised_topic_change and event.user.is_self:
            # bot is authorised to change the name
            authorised_topic_change = True

        if not authorised_topic_change:
            # admins can always change the name
            admins_list = bot.get_config_suboption(event.conv_id, 'admins')
            if event.user_id.chat_id in admins_list:
                authorised_topic_change = True

        if authorised_topic_change:
            bot.memory.set_by_path(memory_topic_path, event.conv_event.new_name)
            bot.memory.save()
            old_name = event.conv_event.new_name

        else:
            hangups_user = bot.get_hangups_user(event.user_id.chat_id)
            logger.warning(
                "unauthorised topic change by %s (%s) in %s, "
                "resetting: %s to: %s",
                hangups_user.full_name, event.user_id.chat_id, event.conv_id,
                event.conv_event.new_name, old_name)

            await command.run(bot, event, *["convrename", "id:" + event.conv_id, old_name])


async def topic(bot, event, *args):
    """locks or unlocks a conversation title."""

    name = ' '.join(args).strip()

    bot.memory.set_by_path(["conv_data", event.conv_id, "topic"], name)
    bot.memory.save()

    if topic == '':
        message = _("Removing topic")
        logger.info("topic cleared from %s", event.conv_id)

    else:
        message = _("Setting topic to '{}'").format(name)
        logger.info("topic for %s set to: %s", event.conv_id, topic)

    # Rename Hangout
    await command.run(bot, event, *["convrename", "id:" + event.conv_id, name])

    return message
