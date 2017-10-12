"""notify user about mentions in attending chats via 1on1 or pushbullet"""

import logging
import re

from pushbullet import PushBullet

from hangupsbot import plugins
from hangupsbot.utils import remove_accents


logger = logging.getLogger(__name__)

EASTER_EGGS = {
    "woot": "w00t",
    "woohoo": "w00h00",
    "lmao": "lma0",
    "rofl": "r0fl",

    "hahahaha": "ha_ha_ha_ha",
    "hehehehe": "he_he_he_he",
    "jejejeje": "je_je_je_je",
    "rsrsrsrs": "rs_rs_rs_rs",

    "happy birthday": "happy_birthday",
    "happy new year": "happy_new_year",

    "xd": "x_d"
}

# cache nicks
_nicks = {}
_nicks_inverse = {}

HELP = {
    'mention': _('alert a @mentioned user'),

    'pushbulletapi': _('allow users to configure pushbullet integration with '
                       'their api key\n'
                       '  {bot_cmd} pushbulletapi [<api key>|false]\n'
                       'example: {bot_cmd} pushbulletapi XYZ'),

    'bemorespecific': _('toggle the "be more specific message" on or off '
                        'permanently'),

    'setnickname': _('allow users to set a nickname for mentions and sync '
                     'relays\n{bot_cmd} setnickname <nickname>\n'
                     'example: {bot_cmd} setnickname alice'),
}

def _initialise(bot):
    """start listening to messages and register admin and user commands

    Args:
        bot: HangupsBot instance
    """
    plugins.register_sync_handler(_handle_mention, "message_once")
    plugins.register_user_command(["pushbulletapi", "setnickname",
                                   "bemorespecific"])
    plugins.register_admin_command(["mention"])
    bot.memory.ensure_path(["user_data"])
    bot.memory.save()
    _populate_nicknames(bot)
    plugins.register_help(HELP)

def _populate_nicknames(bot):
    """Pull the keywords from memory and build an index and reverse index

    Args:
        bot: HangupsBot instance
    """
    for chat_id in bot.memory["user_data"]:
        nickname = bot.user_memory_get(chat_id, "nickname")
        if nickname:
            _nicks[chat_id] = nickname
            _nicks_inverse[nickname.lower()] = chat_id

async def _handle_mention(bot, event, command):
    """forward cleaned @mention names to the main mention function

    Args:
        bot: HangupsBot instance
        event: sync.event.SyncEvent instance
        command: command handler from commands
    """
    # allow mentions to be disabled via global or per-conversation config
    if bot.get_config_suboption(event.conv_id, 'mentions.enabled') is False:
        logger.info("mentions explicitly disabled by config for %s",
                    event.conv_id)
        return

    occurrences = [word for word in set(event.text.split())
                   if word.startswith('@')]
    if not occurrences:
        return

    # minimum length check for @mention
    minimum_length = bot.get_config_suboption(event.conv_id,
                                              'mentionminlength') or 2

    for word in occurrences:
        # strip all special characters
        cleaned_name = ''.join(e for e in word if e.isalnum() or e == "_")
        if len(cleaned_name) < minimum_length:
            _log("@mention '%s' from {full} ({chat}) in {conv} is too short",
                 event, cleaned_name)
            return
        await command.run(bot, event, *["mention", cleaned_name])

def _log(template, event, *args, debug=False):
    """fill the template with info from the event and log it with given args

    available keys in the template: 'conv' (_id), 'full' (_name), 'chat' (_id)

    Args:
        template: string
        event: hangups Event instance
        level: string, logging level
    """
    output = template.format(conv=event.conv_id, full=event.user.full_name,
                             chat=event.user_id.chat_id)
    if debug:
        logger.debug(output, *args)
    else:
        logger.info(output, *args)

async def mention(bot, event, *args):
    """alert a @mentioned user"""

    users_in_chat = event.user_list

    # /bot mention <fragment> test
    noisy_mention_test = len(args) == 2 and args[1] == "test"

    initiator = event.user.id_.chat_id
    try:
        initiator_has_dnd = bot.call_shared("dnd.user_check", initiator)
    except KeyError:
        initiator_has_dnd = False

    # quidproquo: users can only @mention if they themselves are @mentionable
    #  (i.e. have a 1-on-1 with the bot)
    conv_1on1 = await bot.get_1to1(initiator,
                                   context={'initiator_convid': event.conv_id})

    if bot.config.get_option("mentionquidproquo"):
        if conv_1on1:
            if initiator_has_dnd:
                _log("quidproquo: user {full} ({chat}) has DND active", event)
                if noisy_mention_test or bot.get_config_suboption(
                        event.conv_id, 'mentionerrors'):
                    text = _("<b>{}</b>, you cannot @mention anyone until your "
                             "DND status is toggled off.").format(
                                 event.user.full_name)
                    await bot.coro_send_message(event.conv, text)
                return
            else:
                _log("quidproquo: user {full} ({chat}) has 1-on-1", event,
                     debug=True)
        else:
            _log("quidproquo: user {full} ({chat}) has no 1-on-1", event)
            if noisy_mention_test or bot.get_config_suboption(event.conv_id,
                                                              'mentionerrors'):
                text = _("<b>{}</b> cannot @mention anyone until they say "
                         "something to me first.").format(event.user.full_name)
                await bot.coro_send_message(event.conv, text)
            return

    # track mention statistics
    user_tracking = {
        "mentioned":[],
        "ignored":[],
        "failed": {
            "pushbullet": [],
            "one2one": [],
        }
    }

    conv_title = event.display_title
    username = args[0].strip()
    _log('@mention "%s" in "%s" ({conv})', event, username, conv_title)
    username_lower = username.lower()

    # is @all available globally/per-conversation/initiator?
    if username_lower == "all":
        if not bot.get_config_suboption(event.conv.id_, 'mentionall'):

            # global toggle is off/not set, check admins
            _log("@ all in {conv}: disabled/unset global/per-conversation",
                 event, debug=True)
            admins_list = bot.get_config_suboption(event.conv_id, 'admins')
            if event.user_id.chat_id not in admins_list:

                # initiator is not an admin, check whitelist
                _log("@ all in {conv}: user {full} ({chat}) is not admin",
                     event, debug=True)
                all_whitelist = bot.get_config_suboption(event.conv_id,
                                                         'mentionallwhitelist')
                if (all_whitelist is None or
                        event.user_id.chat_id not in all_whitelist):
                    _log("@ all in {conv}: user {full} ({chat}) blocked", event)
                    if conv_1on1:
                        text = _("You are not allowed to mention all users in "
                                 "<b>{}</b>").format(conv_title)
                        await bot.coro_send_message(conv_1on1, text)

                    if (noisy_mention_test or
                            bot.get_config_suboption(event.conv_id,
                                                     'mentionerrors')):
                        text = _("<b>{}</b> blocked from mentioning all users"
                                ).format(event.user.full_name)
                        await bot.coro_send_message(event.conv, text)
                    return
                else:
                    _log(("@ all in {conv}: allowed, "
                          "{full} ({chat}) is whitelisted"), event)
            else:
                _log("@ all in {conv}: allowed, {full} ({chat}) is an admin",
                     event)
        else:
            _log("@ all in {conv}: enabled global/per-conversation", event)

    # generate a list of users to be @mentioned
    exact_nickname_matches = []
    exact_fragment_matches = []
    mention_list = []

    nickname_chat_id = _nicks_inverse.get(username_lower)
    if (nickname_chat_id is not None
            and nickname_chat_id not in event.notified_users
            and any(user.id_.chat_id == nickname_chat_id
                    for user in users_in_chat)):
        exact_nickname_matches.append(bot.get_hangups_user(nickname_chat_id))
        # skip the handling of the user list as we got an exact match
        users_in_chat = []

    for user in users_in_chat:
        user_chat_id = user.id_.chat_id

        if user_chat_id in event.notified_users:
            # prevent duplicate mentions for this event
            _log("suppressing duplicate mention for {full} ({chat})", event,
                 debug=True)
            continue

        u_full = user.full_name

        _normalised_full_lower = remove_accents(u_full.upper()).lower()

        if (username_lower == "all" or

                username_lower in u_full.replace(" ", "").lower() or
                username_lower in _normalised_full_lower.replace(" ", "") or

                username_lower in u_full.replace(" ", "_").lower() or
                username_lower in _normalised_full_lower.replace(" ", "_")):

            logger.debug("user %s (%s) is present", u_full, user_chat_id)

            if user.is_self:
                # bot cannot be @mentioned
                _log("suppressing bot mention by {full} ({chat})", event,
                     debug=True)
                continue

            if user_chat_id == event.user_id.chat_id:
                if noisy_mention_test:
                    # self mention requested
                    _log("noisy_mention_test with @self for {full} ({chat})",
                         event, debug=True)
                    mention_list.append(user)
                continue

            if (bot.memory.exists(["donotdisturb"]) and
                    "dnd.user_check" in bot.shared):
                if bot.call_shared("dnd.user_check", user_chat_id):
                    logger.info("suppressing @mention for %s (%s)", u_full,
                                user_chat_id)
                    user_tracking["ignored"].append(u_full)
                    continue

            if (username_lower in u_full.lower().split() or
                    username_lower in _normalised_full_lower.split()):
                exact_fragment_matches.append(user)

            mention_list.append(user)

    if len(exact_nickname_matches) == 1:
        # prioritise exact nickname matches
        logger.info("prioritising nickname match for %s",
                    exact_nickname_matches[0].full_name)
        mention_list = exact_nickname_matches

    elif len(exact_fragment_matches) == 1:
        # prioritise case-sensitive fragment matches
        logger.info("prioritising single case-sensitive fragment match for %s",
                    exact_fragment_matches[0].full_name)
        mention_list = exact_fragment_matches

    elif (len(exact_fragment_matches) > 1 and
          len(exact_fragment_matches) < len(mention_list)):
        logger.info(
            "prioritising multiple case-sensitive fragment match for %s",
            exact_fragment_matches[0].full_name)
        mention_list = exact_fragment_matches

    # more than one recipient, not @all and more than one user in the recipients
    if (len(mention_list) > 1 and username_lower != "all" and
            len(set([user.id_.chat_id for user in mention_list])) > 1):

        send_multiple_user_message = bot.user_memory_get(
            event.user_id.chat_id, "mentionmultipleusermessage") or True

        if conv_1on1 and (send_multiple_user_message or noisy_mention_test):
            lines = [_('{} users would be mentioned with "@{}"! Be more '
                       'specific. List of matching users:').format(
                           len(mention_list), username, conv_title)]

            for user in mention_list:
                nickname = bot.user_memory_get(user.id_.chat_id, "nickname")
                name = user.full_name.replace(" ", "_")
                if nickname is not None:
                    name += ' (' + nickname + ')'
                lines.append(name)

            lines.append('')
            lines.append(_("<i>To toggle this message on/off, use <b>{} "
                           "bemorespecific</b></i>".format(
                               bot.command_prefix)))

            await bot.coro_send_message(conv_1on1, "\n>".join(lines))

        logger.info("@%s not sent due to multiple recipients", username)
        return #SHORT-CIRCUIT

    source_name = event.user.get_displayname(event.conv_id, text_only=True)
    text = event.text

    # send @mention alerts
    for user in mention_list:
        user_chat_id = user.id_.chat_id
        alert_via_1on1 = True

        # pushbullet integration
        pushbullet_config = bot.user_memory_get(user_chat_id, "pushbullet")
        if (pushbullet_config is not None and
                pushbullet_config["api"] is not None):
            try:
                api = PushBullet(pushbullet_config["api"])
                push = api.push_link(
                    title=_("{} mentioned you in {}").format(
                        source_name, conv_title),
                    body=text,
                    url='https://hangouts.google.com/chat/{}'.format(
                        event.conv_id))
                if isinstance(push, tuple):
                    # backward-compatibility for pushbullet library < 0.8.0
                    success = push[0]
                elif isinstance(push, dict):
                    success = True
                else:
                    logger.error(
                        "unknown return from pushbullet library: %s", push)
                    success = False
            except:               # pushbullet part - pylint:disable=bare-except
                logger.exception("pushbullet error")
                success = False

            if success:
                user_tracking["mentioned"].append(user.full_name)
                logger.info("%s (%s) alerted via pushbullet",
                            user.full_name, user_chat_id)
                alert_via_1on1 = False # disable 1on1 alert
            else:
                user_tracking["failed"]["pushbullet"].append(user.full_name)
                logger.info("pushbullet alert failed for %s (%s)",
                            user.full_name, user_chat_id)

        if alert_via_1on1:
            # send alert with 1on1 conversation
            conv_1on1 = await bot.get_1to1(
                user_chat_id, context={'initiator_convid': event.conv_id})
            if username_lower == "all":
                template = _("<b>{}</b> @mentioned ALL in <i>{}</i> :\n{}")
            else:
                template = _("<b>{}</b> @mentioned you in <i>{}</i> :\n{}")
            if conv_1on1:
                await bot.coro_send_message(
                    conv_1on1, template.format(source_name, conv_title, text))
                event.notified_users.add(user_chat_id)
                user_tracking["mentioned"].append(user.full_name)
                logger.info("%s (%s) alerted via 1on1 (%s)", user.full_name,
                            user_chat_id, conv_1on1.id_)
            else:
                user_tracking["failed"]["one2one"].append(user.full_name)
                if bot.get_config_suboption(event.conv_id, 'mentionerrors'):
                    await bot.coro_send_message(
                        event.conv, _("@mention didn't work for <b>{}</b>. User"
                                      " must say something to me first."
                                     ).format(user.full_name))
                logger.info("user %s (%s) could not be alerted via 1on1",
                            user.full_name, user_chat_id)

    if noisy_mention_test:
        lines = [_("<b>@mentions:</b>")]
        tracking = [
            (_("1-to-1 fail"), user_tracking["failed"]["one2one"]),
            (_("PushBullet fail"), user_tracking["failed"]["pushbullet"]),
            (_("Ignored (DND)"), user_tracking["ignored"]),
            (_("Alerted"), user_tracking["mentioned"])
            ]
        template_tracking = "{info}: <i>{users}</i>"
        for info, values in tracking:
            if not values:
                continue
            lines.append(template_tracking.format(info=info,
                                                  users=", ".join(values)))

        if not user_tracking["mentioned"]:
            lines.append(_("Nobody was successfully @mentioned ;-("))

        if user_tracking["failed"]["one2one"]:
            lines.append(_("Users failing 1-to-1 need to say something to me "
                           "privately first."))

        await bot.coro_send_message(event.conv, '<br>'.join(lines))

def pushbulletapi(bot, event, *args):
    """allow users to configure pushbullet integration with api key"""

    if len(args) == 1:
        value = args[0]
        if value.lower() in ('false', '0', '-1'):
            value = None
            text = _("deactivating pushbullet integration")
        else:
            value = {"api": value}
            text = _("setting pushbullet api key")

        bot.user_memory_set(event.user_id.chat_id, "pushbullet", value)
    else:
        text = _("pushbullet configuration not changed")

    return text


def bemorespecific(bot, event, *dummys):
    """toggle the "be more specific message" on and off permanently"""
    user_setting = bot.user_memory_get(event.user_id.chat_id,
                                       "mentionmultipleusermessage")
    if user_setting is None:
        # it is first time, the user triggered the command
        _toggle = False
    else:
        _toggle = not user_setting

    bot.user_memory_set(event.user_id.chat_id, "mentionmultipleusermessage",
                        _toggle)
    if _toggle:
        text = _('<em>"be more specific" for mentions toggled ON</em>')
    else:
        text = _('<em>"be more specific" for mentions toggled OFF</em>')

    return text



def setnickname(bot, event, *args):
    """allow users to set a nickname for mentions and sync relays"""

    truncatelength = 16 # What should the maximum length of the nickname be?
    minlength = 2 # What should the minimum length of the nickname be?

    chat_id = event.user_id.chat_id

    nickname = ' '.join(args).strip()

    # Strip all non-alphanumeric characters
    nickname = re.sub('[^0-9a-zA-Z-_]+', '', nickname)

    # Truncate nickname
    nickname = nickname[0:truncatelength]

    if nickname and len(nickname) < minlength: # Check minimum length
        return _("Error: Minimum length of nickname is {} characters. "
                 "Only alphabetical and numeric characters allowed."
                ).format(minlength)

    # perform hard-coded substitution on words that trigger easter eggs
    for original in EASTER_EGGS:
        if original in nickname.lower():
            pattern = re.compile(original, re.IGNORECASE)
            nickname = pattern.sub(EASTER_EGGS[original], nickname)

    text = None
    if not nickname:
        old_nickname = _nicks.pop(chat_id, None)
        if old_nickname is None:
            text = _("<i>Nickname is already unset.</i>")
        else:
            _nicks_inverse.pop(old_nickname, None)
            text = _('<i>Removing nickname "{}"</i>').format(old_nickname)
            path = ['user_data', chat_id]
            bot.memory.pop_by_path(path + ['nickname'])
            bot.memory.pop_by_path(path + ['label'])

    elif nickname.lower() in _nicks_inverse:
        nickname_user_id = _nicks_inverse[nickname.lower()]

        if nickname_user_id != chat_id:
            text = _('<i>Nickname <b>"{}"</b> is already in use by {}').format(
                nickname, bot.get_hangups_user(nickname_user_id).full_name)
        elif nickname == _nicks[chat_id]:
            text = _('<i>Your nickname is already <b>"{}"</b></i>').format(
                nickname)

    if text is not None:
        return text

    # save new nickname
    bot.user_memory_set(chat_id, "nickname", nickname)

    # Update nicks cache with new nickname
    old_nickname = _nicks.pop(chat_id, None)
    _nicks_inverse.pop(old_nickname, None)
    text = (_("Setting nickname to '{}'").format(nickname)
            if old_nickname is None else
            _("Updating nickname to '{}'").format(nickname))
    _nicks[chat_id] = nickname
    _nicks_inverse[nickname.lower()] = chat_id

    # cache the new display name
    label = "{} ({})".format(event.user.first_name, nickname)
    bot.user_memory_set(chat_id, "label", label)

    return text
