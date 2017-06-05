"""Allows the user to configure the bot to watch for hangout renames
and change the name back to a default name accordingly"""

import asyncio, logging

import hangups

import plugins

from commands import command


logger = logging.getLogger(__name__)


def _initialise(bot):
    plugins.register_handler(_watch_rename, type="rename")
    plugins.register_admin_command(["topic"])


async def _watch_rename(bot, event, command):

    memory_topic_path = ["conv_data", event.conv_id, "topic"]

    topic = False
    if bot.memory.exists(memory_topic_path):
        topic = bot.memory.get_by_path(memory_topic_path)

    if topic:
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
            topic = event.conv_event.new_name

        if event.conv_event.new_name != topic:
            hangups_user = bot.get_hangups_user(event.user_id.chat_id)
            logger.warning(
                "unauthorised topic change by {} ({}) in {}, resetting: {} to: {}"
                    .format( hangups_user.full_name,
                             event.user_id.chat_id,
                             event.conv_id,
                             event.conv_event.new_name,
                             topic ))

            await command.run(bot, event, *["convrename", "id:" + event.conv_id, topic])


async def topic(bot, event, *args):
    """locks a conversation title. if no parameters supplied, clear and unlock the title"""

    topic = ' '.join(args).strip()

    bot.memory.set_by_path(["conv_data", event.conv_id, "topic"], topic)
    bot.memory.save()

    if(topic == ''):
        message = _("Removing topic")
        logger.info("topic cleared from {}".format(event.conv_id))

    else:
        message = _("Setting topic to '{}'").format(topic)
        logger.info("topic for {} set to: {}".format(event.conv_id, topic))

    """Rename Hangout"""
    await command.run(bot, event, *["convrename", "id:" + event.conv_id, topic])

    return message
