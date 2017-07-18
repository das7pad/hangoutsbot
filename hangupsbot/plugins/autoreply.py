# TODO(das7pad): refactor needed
import asyncio
import logging
import json
import random
import re

import hangups

import plugins

import sync.event

logger = logging.getLogger(__name__)

HELP = {
    "autoreply": _(
        "adds or removes an autoreply.\nFormat:\nadd:\n {bot_cmd} autoreply add"
        ' [["question1","question2"],"answer"]\nremove:\n {bot_cmd} autoreply '
        'remove [["question"],"answer"]\nview all autoreplies:\n {bot_cmd} '
        "autoreply")
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
        logger.debug("explicitly disabled by tag for {} {}".format(event.user_id.chat_id, event.conv.id_))
        return

    """Handle autoreplies to keywords in messages"""

    if isinstance(event, sync.event.SyncEventMembership):
        if event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_JOIN:
            event_type = "JOIN"
        else:
            event_type = "LEAVE"
    elif isinstance(event, sync.event.SyncEvent):
        event_type = "MESSAGE"
    elif isinstance(event.conv_event, hangups.RenameEvent):
        event_type = "RENAME"
    else:
        raise RuntimeError("unhandled event type")

    # get_config_suboption returns the convo specific autoreply settings. If none set, it returns the global settings.
    autoreplies_list = bot.get_config_suboption(event.conv_id, 'autoreplies')

    """option to merge per-conversation and global autoreplies, by:
    * tagging a conversation with "autoreplies-merge" explicitly or by wildcard conv tag
    * setting global config key: autoreplies.merge = true
    note: you must also define the appropriate autoreply keys for a specific conversation
    (by default per-conversation autoreplies replaces global autoreplies settings completely)"""

    tagged_autoreplies_merge = "autoreplies-merge" in bot.tags.convactive(event.conv_id)
    config_autoreplies_merge = bot.config.get_option('autoreplies.merge') or False

    if tagged_autoreplies_merge or config_autoreplies_merge:

        # load any global settings as well
        autoreplies_list_global = bot.config.get_option('autoreplies')

        # If the global settings loaded from get_config_suboption then we now have them twice and don't need them, so can be ignored.
        if autoreplies_list_global and (set([ frozenset([
                frozenset(x) if isinstance(x, list) else x,
                frozenset(y) if isinstance(y, list) else y ]) for x, y in autoreplies_list_global ])
                != set([ frozenset([ frozenset(x) if isinstance(x, list) else x,
                         frozenset(y) if isinstance(y, list) else y ]) for x, y in autoreplies_list ])):

            add_to_autoreplies = []

            # If the two are different, then iterate through each of the triggers in the global list and if they
            # match any of the triggers in the convo list then discard them.
            # Any remaining at the end of the loop are added to the first list to form a consolidated list
            # of per-convo and global triggers & replies, with per-convo taking precident.

            # Loop through list of global triggers e.g. ["hi","hello","hey"],["baf","BAF"].
            for kwds_gbl, sentences_gbl in autoreplies_list_global:
                overlap = False
                for kwds_lcl, sentences_lcl in autoreplies_list:
                    if type(kwds_gbl) is type(kwds_lcl) is list and (set(kwds_gbl) & set(kwds_lcl)):
                        overlap = True
                        break
                if not overlap:
                    add_to_autoreplies.extend( [[kwds_gbl, sentences_gbl]] )

            # Extend original list with non-disgarded entries.
            autoreplies_list.extend( add_to_autoreplies )

    if autoreplies_list:
        for kwds, sentences in autoreplies_list:

            if isinstance(sentences, list):
                message = random.choice(sentences)
            else:
                message = sentences

            if isinstance(kwds, list):
                for kw in kwds:
                    if _words_in_text(kw, event.text) or kw == "*":
                        logger.info("matched chat: {}".format(kw))
                        await send_reply(bot, event, message)
                        break

            elif event_type == kwds:
                logger.info("matched event: {}".format(kwds))
                await send_reply(bot, event, message)


async def send_reply(bot, event, message):
    if not isinstance(message, str):
        return

    values = {"event": event,
              "conv_title": bot.conversations.get_name(
                  event.conv_id, _("Unidentified Conversation"))}

    if "participant_ids" in dir(event.conv_event):
        values["participants"] = [ event.conv.get_user(user_id)
                                   for user_id in event.conv_event.participant_ids ]
        values["participants_namelist"] = ", ".join([ u.full_name for u in values["participants"] ])

    # tldr plugin integration: inject current conversation tldr text into auto-reply
    if '{tldr}' in message:
        args = {'conv_id': event.conv_id, 'params': ''}
        try:
            values["tldr"] = bot.call_shared("plugin_tldr_shared", bot, args)
        except KeyError:
            values["tldr"] = "**[TLDR UNAVAILABLE]**" # prevents exception
            logger.warning("tldr plugin is not loaded")
            pass

    envelopes = []

    if message.startswith(("ONE_TO_ONE:", "HOST_ONE_TO_ONE:")):
        message = message.split(':', 1)[-1]
        target_conv = await bot.get_1to1(event.user.id_.chat_id)
        if not target_conv:
            logger.error("1-to-1 unavailable for {} ({})".format( event.user.full_name,
                                                                  event.user.id_.chat_id ))
            return False
        envelopes.append((target_conv, message.format(**values)))

    elif message.startswith("GUEST_ONE_TO_ONE:"):
        message = message.split(':', 1)[-1]
        for guest in values["participants"]:
            target_conv = await bot.get_1to1(guest.id_.chat_id)
            if not target_conv:
                logger.error("1-to-1 unavailable for {} ({})".format( guest.full_name,
                                                                      guest.id_.chat_id ))
                return False
            values["guest"] = guest # add the guest as extra info
            envelopes.append((target_conv, message.format(**values)))

    else:
        envelopes.append((event.conv, message.format(**values)))

    for send in envelopes:
        conv_target, message = send

        try:
            image_id = await bot.call_shared('image_validate_and_upload_single',
                                             message,
                                             reject_googleusercontent=False)
        except KeyError:
            logger.warning("image plugin not loaded - using in-built fallback")
            image_id = await image_validate_and_upload_single(message, bot)

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

    regexword = r"(?<!\w)" + word + r"(?!\w)"

    return True if re.search(regexword, text, re.IGNORECASE) else False


def autoreply(bot, event, cmd=None, *args):
    """adds or removes an autoreply from config.

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        cmd: string, the first argument passed after the command
        args: tuple of strings, additional words as the new/old autoreply entry

    Returns:
        string
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


"""FALLBACK CODE FOR IMAGE LINK VALIDATION AND UPLOAD
* CODE IS DEPRECATED - DO NOT CHANGE OR ALTER
* CODE MAY BE REMOVED AT ANY TIME
* FOR FUTURE-PROOFING, INCLUDE [image] PLUGIN IN YOUR CONFIG.JSON
"""

import aiohttp, io, os, re

def image_validate_link(image_uri, reject_googleusercontent=True):
    """
    validate and possibly mangle supplied image link
    returns False, if not an image link
            <string image uri>
    """

    if " " in image_uri:
        """immediately reject anything with non url-encoded spaces (%20)"""
        return False

    probable_image_link = False

    image_uri_lower = image_uri.lower()

    if re.match(r"^(https?://)?([a-z0-9.]*?\.)?imgur.com/", image_uri_lower, re.IGNORECASE):
        """imgur links can be supplied with/without protocol and extension"""
        probable_image_link = True

    elif image_uri_lower.startswith(("http://", "https://", "//")) and image_uri_lower.endswith((".png", ".gif", ".gifv", ".jpg", ".jpeg")):
        """other image links must have protocol and end with valid extension"""
        probable_image_link = True

    if probable_image_link and reject_googleusercontent and ".googleusercontent." in image_uri_lower:
        """reject links posted by google to prevent endless attachment loop"""
        logger.debug("rejected link {} with googleusercontent".format(image_uri))
        return False

    if probable_image_link:

        """special handler for imgur links"""
        if "imgur.com" in image_uri:
            if not image_uri.endswith((".jpg", ".gif", "gifv", "webm", "png")):
                image_uri = image_uri + ".gif"
            image_uri = "https://i.imgur.com/" + os.path.basename(image_uri)

            """imgur wraps animations in player, force the actual image resource"""
            image_uri = image_uri.replace(".webm",".gif")
            image_uri = image_uri.replace(".gifv",".gif")

        logger.debug('{} seems to be a valid image link'.format(image_uri))

        return image_uri

    return False

@asyncio.coroutine
def image_upload_single(image_uri, bot):
    logger.info("getting {}".format(image_uri))
    filename = os.path.basename(image_uri)
    r = yield from aiohttp.request('get', image_uri)
    raw = yield from r.read()
    image_data = io.BytesIO(raw)
    image_id = yield from bot._client.upload_image(image_data, filename=filename)
    return image_id

@asyncio.coroutine
def image_validate_and_upload_single(text, bot, reject_googleusercontent=True):
    image_id = False
    image_link = image_validate_link(text, reject_googleusercontent=reject_googleusercontent)
    if image_link:
        image_id = yield from image_upload_single(image_link, bot)
    return image_id
