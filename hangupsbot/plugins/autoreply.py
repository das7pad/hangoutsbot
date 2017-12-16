# TODO(das7pad): refactor needed
import logging
import json
import random
import re

import hangups

from hangupsbot import plugins
from hangupsbot.sync import event as sync_events

from hangupsbot.plugins.image import image_validate_and_upload_single

logger = logging.getLogger(__name__)

HELP = {
    "autoreply": _(
        "adds or removes an autoreply.\nFormat:\nadd:\n {bot_cmd} autoreply add"
        ' [["question1","question2"],"answer"]\nremove:\n {bot_cmd} autoreply '
        'remove [["question"],"answer"]\nview all autoreplies:\n {bot_cmd} '
        "autoreply"),
}

def _initialise(bot):
    """register the handlers, autoreply command and the help entry"""
    plugins.register_sync_handler(_handle_autoreply, "message_once")
    plugins.register_sync_handler(_handle_autoreply, "rename")
    plugins.register_admin_command(["autoreply"])
    plugins.register_help(HELP)
    bot.config.set_defaults({"autoreplies_enabled": True})

async def _handle_autoreply(bot, event):
    config_autoreplies = bot.get_config_suboption(event.conv.id_, 'autoreplies_enabled')
    tagged_autoreplies = "autoreplies-enable" in bot.tags.useractive(event.user_id.chat_id, event.conv.id_)

    if not (config_autoreplies or tagged_autoreplies):
        return

    if "autoreplies-disable" in bot.tags.useractive(event.user_id.chat_id, event.conv.id_):
        logger.debug("explicitly disabled by tag for %s %s",
                     event.user_id.chat_id, event.conv_id)
        return

    # Handle autoreplies to keywords in messages

    if isinstance(event, sync_events.SyncEventMembership):
        if event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_JOIN:
            event_type = "JOIN"
        else:
            event_type = "LEAVE"
    elif isinstance(event, sync_events.SyncEvent):
        event_type = "MESSAGE"
    elif isinstance(event.conv_event, hangups.RenameEvent):
        event_type = "RENAME"
    else:
        raise RuntimeError("unhandled event type")

    # get_config_suboption returns the conv specific autoreply settings. If none set, it returns the global settings.
    autoreplies_list = bot.get_config_suboption(event.conv_id, 'autoreplies')

    # option to merge per-conversation and global autoreplies, by:
    # * tagging a conversation with "autoreplies-merge" explicitly or by wildcard conv tag
    # * setting global config key: autoreplies.merge = true
    # note: you must also define the appropriate autoreply keys for a specific conversation
    # (by default per-conversation autoreplies replaces global autoreplies settings completely)

    tagged_autoreplies_merge = "autoreplies-merge" in bot.tags.convactive(event.conv_id)
    config_autoreplies_merge = bot.config.get_option('autoreplies.merge') or False

    if tagged_autoreplies_merge or config_autoreplies_merge:

        # load any global settings as well
        autoreplies_list_global = bot.config.get_option('autoreplies')

        # If the global settings loaded from get_config_suboption then we now have them twice and don't need them, so can be ignored.
        if (autoreplies_list_global
                and (set([frozenset([frozenset(x) if isinstance(x, list) else x,
                                     frozenset(y) if isinstance(y, list) else y])
                          for x, y in autoreplies_list_global])
                     != set([frozenset([frozenset(x) if isinstance(x, list) else x,
                                        frozenset(y) if isinstance(y, list) else y])
                             for x, y in autoreplies_list]))):

            add_to_autoreplies = []

            # If the two are different, then iterate through each of the triggers in the global list and if they
            # match any of the triggers in the conv list then discard them.
            # Any remaining at the end of the loop are added to the first list to form a consolidated list
            # of per-conv and global triggers & replies, with per-conv taking precedent.

            # Loop through list of global triggers e.g. ["hi","hello","hey"],["baf","BAF"].
            for kwds_gbl, sentences_gbl in autoreplies_list_global:
                overlap = False
                for kwds_lcl, dummy in autoreplies_list:
                    if type(kwds_gbl) is type(kwds_lcl) is list and (set(kwds_gbl) & set(kwds_lcl)):
                        overlap = True
                        break
                if not overlap:
                    add_to_autoreplies.extend([[kwds_gbl, sentences_gbl]])

            # Extend original list with non-discarded entries.
            autoreplies_list.extend(add_to_autoreplies)

    if autoreplies_list:
        for kwds, sentences in autoreplies_list:

            if isinstance(sentences, list):
                message = random.choice(sentences)
            else:
                message = sentences

            if isinstance(kwds, list):
                for trigger in kwds:
                    if _words_in_text(trigger, event.text) or trigger == "*":
                        logger.info("matched chat: %s", trigger)
                        await send_reply(bot, event, message)
                        break

            elif event_type == kwds:
                logger.info("matched event: %s", kwds)
                await send_reply(bot, event, message)


async def send_reply(bot, event, message):
    if not isinstance(message, str):
        return

    values = {"event": event,
              "conv_title": bot.conversations.get_name(
                  event.conv_id, _("Unidentified Conversation"))}

    if "participant_ids" in dir(event.conv_event):
        values["participants"] = [event.conv.get_user(user_id)
                                  for user_id in event.conv_event.participant_ids]
        values["participants_namelist"] = ", ".join([u.full_name for u in values["participants"]])

    # tldr plugin integration: inject current conversation tldr text into auto-reply
    if '{tldr}' in message:
        args = {'conv_id': event.conv_id, 'params': ''}
        try:
            values["tldr"] = bot.call_shared("plugin_tldr_shared", bot, args)
        except KeyError:
            values["tldr"] = "**[TLDR UNAVAILABLE]**" # prevents exception
            logger.warning("tldr plugin is not loaded")

    envelopes = []

    if message.startswith(("ONE_TO_ONE:", "HOST_ONE_TO_ONE:")):
        message = message.split(':', 1)[-1]
        target_conv = await bot.get_1to1(event.user.id_.chat_id)
        if not target_conv:
            logger.error("1-to-1 unavailable for %s (%s)",
                         event.user.full_name, event.user.id_.chat_id)
            return False
        envelopes.append((target_conv, message.format(**values)))

    elif message.startswith("GUEST_ONE_TO_ONE:"):
        message = message.split(':', 1)[-1]
        for guest in values["participants"]:
            target_conv = await bot.get_1to1(guest.id_.chat_id)
            if not target_conv:
                logger.error("1-to-1 unavailable for %s (%s)",
                             guest.full_name, guest.id_.chat_id)
                return False
            values["guest"] = guest # add the guest as extra info
            envelopes.append((target_conv, message.format(**values)))

    else:
        envelopes.append((event.conv, message.format(**values)))

    for send in envelopes:
        conv_target, message = send

        image_id = await image_validate_and_upload_single(
            message, reject_googleusercontent=False)

        if image_id:
            await bot.coro_send_message(conv_target, None, image_id=image_id)
        else:
            await bot.coro_send_message(conv_target, message)

    return True


def _words_in_text(word, text):
    """Return True if word is in text"""

    if word.startswith("regex:"):
        word = word[6:]
    else:
        word = re.escape(word)

    regex = r"(?<!\w)" + word + r"(?!\w)"

    return True if re.search(regex, text, re.IGNORECASE) else False


def autoreply(bot, event, cmd=None, *args):
    """adds or removes an autoreply from config.

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        event (event.ConversationEvent): a message container
        cmd (str): the first argument passed after the command
        args (str): the new/old autoreply entry

    Returns:
        str: command output
    """
    argument = " ".join(args)
    html = None
    value = bot.get_config_suboption(event.conv_id, "autoreplies")

    if cmd == 'add':
        if isinstance(value, list):
            value.append(json.loads(argument))
            bot.config.save()
        else:
            html = "Append failed on non-list"
    elif cmd == 'remove':
        if isinstance(value, list):
            value.remove(json.loads(argument))
            bot.config.save()
        else:
            html = "Remove failed on non-list"

    if html is None:
        html = "<b>Autoreply config:</b>\n{}".format(value)

    return html
