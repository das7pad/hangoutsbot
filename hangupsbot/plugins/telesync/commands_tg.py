"""Telegram-commands"""
__author__ = 'das7pad@outlook.com'

import asyncio
import logging

import telepot.exception
from telepot.namedtuple import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from hangupsbot.commands import command
from hangupsbot.sync import SYNC_CONFIG_KEYS
from hangupsbot.sync.event import FakeEvent
from hangupsbot.sync.exceptions import ProfilesyncAlreadyCompleted
from hangupsbot.sync.user import SyncUser
from hangupsbot.sync.utils import get_sync_config_entry


logger = logging.getLogger(__name__)

# rights for /restrict_user
NO_SENDING_RIGHTS = {
    'can_send_messages': False,
    'can_send_media_messages': False,
    'can_send_other_messages': False,
    'can_add_web_page_previews': False,
}
NO_MEDIA_RIGHTS = {
    'can_send_media_messages': False,
    'can_send_messages': True,
    'can_send_other_messages': True,
    'can_add_web_page_previews': True,
}
NO_STICKER_RIGHTS = {
    'can_send_other_messages': False,
    'can_send_messages': True,
    'can_send_media_messages': True,
    'can_add_web_page_previews': True,
}
NO_WEBPREVIEW_RIGHTS = {
    'can_add_web_page_previews': False,
    'can_send_messages': True,
    'can_send_media_messages': True,
    'can_send_other_messages': True,
}
NO_WEBPREVIEW_AND_STICKER_RIGHTS = {
    'can_send_other_messages': False,
    'can_add_web_page_previews': False,
    'can_send_messages': True,
    'can_send_media_messages': True,
}
FULL_RIGHTS = {
    'can_send_messages': True,
    'can_send_media_messages': True,
    'can_send_other_messages': True,
    'can_add_web_page_previews': True,
}
RESTRICT_OPTIONS = ('false', 'messages', 'media', 'sticker', 'websites',
                    'sticker+websites')


def ensure_admin(tg_bot, msg):
    """return whether the user is admin, and respond if be_quiet is off

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper

    Returns:
        bool: True if user is Admin, otherwise False
    """
    if not msg.user.usr_id in tg_bot.config('admins'):
        if not tg_bot.config('be_quiet'):
            tg_bot.send_html(msg.chat_id, _('This command is admin-only!'))
        return False
    return True


def ensure_private(tg_bot, msg):
    """return whether the chat is private, and respond if be_quiet is off

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper

    Returns:
        bool: True if chat is of type private, otherwise False
    """
    if msg.chat_type != 'private':
        if not tg_bot.config('be_quiet'):
            tg_bot.send_html(msg.chat_id,
                             _('Issue again in a private chat:\n'
                               'Tap on my name then hit the message icon'))
        return False
    return True


def ensure_args(tg_bot, tg_chat_id, args, between=None, at_least=None):
    """check the number of arguments, and respond if be_quiet is off

    Args:
        tg_bot (core.TelegramBot): the running instance
        tg_chat_id (mixed): str or int, conversation identifier
        args (tuple[str]): command tokens
        between (tuple): tuple of int, lower/higher limit for the amount of args
        at_least (int): amount of args that are required at least

    Returns:
        bool: True if the number is correct, otherwise False
    """
    if between is None and at_least is None:
        between = (1, 1)
    if ((between is not None and
         len(args) not in range(between[0], between[1] + 1)) or
            (at_least is not None and len(args) < at_least)):
        if not tg_bot.config('be_quiet'):
            tg_bot.send_html(tg_chat_id, _('Check arguments.'))
        return False
    return True


async def command_start(tg_bot, msg, *args):
    """answer with the start message and check for deep linking, private only

    /start [syncprofile]

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if ensure_private(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         tg_bot.config('start_message').format(
                             name=msg.user.full_name,
                             botusername=tg_bot.user.username,
                             botname=tg_bot.user.full_name))

    if 'syncprofile' in args:
        await command_sync_profile(tg_bot, msg)


async def command_cancel(tg_bot, msg, *dummys):
    """hide the custom keyboard

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    await tg_bot.sendMessage(
        msg.chat_id, _('canceled'),
        reply_markup=ReplyKeyboardRemove(remove_keyboard=True))


async def command_whoami(tg_bot, msg, *dummys):
    """answer with user_id of request message, private only

    /whereami

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if ensure_private(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         _("Your Telegram user id is '%s'") % msg.user.usr_id)


async def command_whereami(tg_bot, msg, *dummys):
    """answer with current tg_chat_id, admin only

    /whereami

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if ensure_admin(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         _("This chat has the id '{}'").format(msg.chat_id))


async def command_whois(tg_bot, msg, *args):
    """get the Telegram user id of a given user

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a received message
        args (str): the search term
    """
    if not ensure_args(tg_bot, msg.chat_id, args):
        return

    term = ' '.join(args).lower()
    users = tg_bot.bot.memory.get_by_path(['telesync', 'user_data'])
    for user_id, data in users.items():
        user = await tg_bot.get_tg_user(user_id, msg.chat_id)
        if term in repr(data).lower() or term in str(user).lower():
            name = user.get_displayname(user.identifier)
            text = _('User <i>{name}</i> has the id "{tg_id}"').format(
                name=name, tg_id=user_id)
            break
    else:
        text = _('Could not find a user matching "%s"') % term
    tg_bot.send_html(msg.chat_id, text)


async def command_set_sync_ho(tg_bot, msg, *args):
    """setup s sync with a given hangout

    /setsyncho <hangout conv_id>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    one_way = _('oneway') in args
    channel = _('channel') in args
    args = (tuple(set(args) - {_('oneway'), _('channel')})
            if one_way or channel else args)

    if not ensure_args(tg_bot, msg.chat_id, args):
        return

    bot = tg_bot.bot
    target = args[0]
    lines = []
    tg2ho = bot.memory.get_by_path(['telesync', ('channel2ho' if channel
                                                 else 'tg2ho')])
    targets = tg2ho.setdefault(msg.chat_id, [])
    if target in targets:
        lines.append(_("TG -> HO: target '{}' already set").format(target))
    else:
        targets.append(target)
        lines.append(_("TG -> HO: target '{}' added".format(target)))

    if not one_way:
        ho2tg = bot.memory.get_by_path(['telesync', 'ho2tg'])
        targets = ho2tg.setdefault(target, [])
        if msg.chat_id in targets:
            lines.append(_("TG <- HO: sync already set"))
        else:
            lines.append(_("TG <- HO: chat added"))
            targets.append(msg.chat_id)

    bot.memory.save()

    tg_bot.send_html(msg.chat_id, '\n'.join(lines))


async def command_clear_sync_ho(tg_bot, msg, *args):
    """unset sync for current chat

    /clearsyncho <conv_ids>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    bot = tg_bot.bot
    if not ensure_admin(tg_bot, msg):
        return

    lines = []
    one_way = _('oneway') in args
    channel = _('channel') in args
    args = (tuple(set(args) - {_('oneway'), _('channel')})
            if one_way or channel else args)

    tg2ho = bot.memory.get_by_path(['telesync', ('channel2ho' if channel
                                                 else 'tg2ho')])
    targets = tg2ho.setdefault(msg.chat_id, [])

    if not args:
        args = tuple(targets)

    path_ho2tg = ['telesync', 'ho2tg']
    ho2tg = bot.memory.get_by_path(path_ho2tg)

    for conv_id in args:
        if conv_id in targets:
            targets.remove(args[0])
            lines.append(_('TG -> HO: target "%s" removed') % conv_id)
        else:
            lines.append(_('TG -> HO: "%s" was not a target') % conv_id)

        if one_way:
            continue

        if conv_id in ho2tg and msg.chat_id in ho2tg[conv_id]:
            ho2tg[conv_id].remove(msg.chat_id)
            lines.append(_('TG <- HO: chat removed from "%s"') % conv_id)
            if not ho2tg[conv_id]:
                bot.memory.pop_by_path(path_ho2tg + [conv_id])
        else:
            lines.append(_('TG <- HO: chat was no target of "%s"') % conv_id)

    if not targets:
        tg2ho.pop(msg.chat_id)

    bot.memory.save()
    text = '\n'.join(lines) or _('No syncs to clear found')

    tg_bot.send_html(msg.chat_id, text)


async def command_add_admin(tg_bot, msg, *args):
    """add admin id to admin list if not present

    /addadmin <tg_user_id>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    if not ensure_args(tg_bot, msg.chat_id, args):
        return

    new_admin = args[0]
    if new_admin not in tg_bot.config('admins'):
        tg_bot.config('admins', False).append(new_admin)
        tg_bot.bot.config.save()
        text = _('User added to admins')
    else:
        text = _('User is already an admin')

    tg_bot.send_html(msg.chat_id, text)


async def command_remove_admin(tg_bot, msg, *args):
    """pop admin id if present in admin list

    /removeadmin <tg_user_id>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    if not ensure_args(tg_bot, msg.chat_id, args):
        return

    old_admin = args[0]
    if old_admin in tg_bot.config('admins'):
        tg_bot.config('admins', False).remove(old_admin)
        tg_bot.bot.config.save()
        text = _('User removed from admins')
    else:
        text = _('User is not an admin')

    tg_bot.send_html(msg.chat_id, text)


async def command_tldr(tg_bot, msg, *args):
    """get tldr for connected conv by manipulating the message text

    /tldr

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens

    Returns:
        bool: True
    """
    msg.text = '{bot_cmd} tldr {args}'.format(bot_cmd=tg_bot.bot.command_prefix,
                                              args=' '.join(args)).strip()
    if msg.user.id_.chat_id == 'sync':
        # a valid chat_id is required to run commands
        chat_id = tg_bot.bot.user_self()['chat_id']
        msg.user = SyncUser(user_id=chat_id)
        msg.user.is_self = False

    # sync the message text to get the tldr
    return True


async def command_sync_profile(tg_bot, msg, *dummys):
    """init profilesync, needs confirmation via pHO

    /syncprofile

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if not ensure_private(tg_bot, msg):
        return

    bot = tg_bot.bot
    user_id = msg.user.usr_id
    base_path = ['profilesync', 'telesync']

    if bot.memory.exists(base_path + ['2ho', user_id]):
        text = _('Your profile is already linked to a G+Profile, use '
                 '/unsyncprofile to unlink your profiles')
        tg_bot.send_html(user_id, text)
        return

    if bot.memory.exists(base_path + ['pending_2ho', user_id]):
        await tg_bot.profilesync_info(user_id, is_reminder=True)
        return

    bot.sync.start_profile_sync('telesync', user_id)

    await tg_bot.profilesync_info(user_id)


async def command_set_sync_profile(tg_bot, msg, *args):
    """init a profilesync for a different user

    /setsyncprofile <tgID> <G+ID> [1on1split]

    Args:
        tg_bot (core.TelegramBot): the currently running instance
        msg (message.Message): a text message event
        args (str): arguments that were passed to the command
    """
    if not ensure_admin(tg_bot, msg):
        return

    if not ensure_args(tg_bot, msg.chat_id, args, between=(2, 3)):
        return

    bot = tg_bot.bot
    tg_id = args[0]
    g_id = args[1]
    # assume that G+ user ids [22digits] are longer than telegram user ids [<10]
    if len(tg_id) > len(g_id):
        tg_id, g_id = g_id, tg_id

    split_1on1 = ('1on1split' in args
                  or '1to1split' in args
                  or '[1on1split]' in args)

    if not (tg_id.isdigit() and g_id.isdigit()):
        text = _('Check command arguments, expected two user ids:\n'
                 '`/setsyncprofile <tgID> <G+ID> [1on1split]`')
        tg_bot.send_html(msg.chat_id, text)
        return

    try:
        await bot.sync.complete_profile_sync(
            platform='telesync', chat_id=g_id, remote_user=tg_id,
            split_1on1s=split_1on1)
    except ProfilesyncAlreadyCompleted:
        text = _('The profile is already linked to a G+Profile')
        tg_bot.send_html(msg.chat_id, text)
        return

    if bot.memory.exists(['telesync', 'user_data', tg_id]):
        tg_name = (await tg_bot.get_tg_user(tg_id)).full_name
    else:
        tg_name = 'unknown'

    g_plus_name = bot.get_hangups_user(g_id).full_name

    text = _(
        'Synced the profile of G+ User <b>{g_plus_name}</b> [{g_id}] to Telegram'
        ' User <b>{tg_name}</b> [{tg_id}].'
    ).format(
        tg_id=tg_id,
        tg_name=tg_name,
        g_id=g_id,
        g_plus_name=g_plus_name,
    )
    tg_bot.send_html(msg.chat_id, text)


async def command_unsync_profile(tg_bot, msg, *dummys):
    """split tg and ho-profile

    /unsyncprofile

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if not ensure_private(tg_bot, msg):
        return

    user_id = msg.user.usr_id
    base_path = ['profilesync', 'telesync']
    bot = tg_bot.bot

    if bot.memory.exists(base_path + ['2ho', user_id]):
        ho_chat_id = bot.memory.pop_by_path(base_path + ['2ho', user_id])
        bot.memory.pop_by_path(base_path + ['ho2', ho_chat_id])

        # cleanup the 1on1 sync, if one was set
        conv_1on1 = bot.user_memory_get(ho_chat_id, '1on1')
        if (bot.memory.exists(['telesync', 'tg2ho', user_id]) and
                bot.memory.exists(['telesync', 'ho2tg', conv_1on1])):
            bot.memory.pop_by_path(['telesync', 'tg2ho', user_id])
            bot.memory.pop_by_path(['telesync', 'ho2tg', conv_1on1])
        bot.memory.save()
        text = _('Telegram and G+Profile are no more linked.')

    elif bot.memory.exists(base_path + ['pending_2ho', user_id]):
        token = bot.memory.pop_by_path(base_path + ['pending_2ho', user_id])
        bot.memory.pop_by_path(base_path + ['pending_ho2', token])
        bot.memory.pop_by_path(['profilesync', '_pending_', token])
        bot.memory.save()
        text = _('Profilesync canceled.')

    else:
        text = _('There is no G+Profile connected to your Telegram Profile.'
                 '\nUse /syncprofile to connect one')

    tg_bot.send_html(msg.chat_id, text)


async def command_get_me(tg_bot, msg, *dummys):
    """send back info to bot user: id, name, username

    /getme

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    tg_bot.send_html(
        msg.chat_id,
        'id: {usr_id}, name: {name}, username: @{username}'.format(
            usr_id=tg_bot.user.usr_id, name=tg_bot.user.first_name,
            username=tg_bot.user.username))


async def command_get_admins(tg_bot, msg, *dummys):
    """send back a formatted list of Admins

    /getadmins

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    admin_users = []
    max_name_length = 0
    for admin_id in tg_bot.config('admins'):
        sync_user = await tg_bot.get_tg_user(user_id=admin_id, gpluslink=True)

        admin_users.append(sync_user)

        # update name length
        if len(sync_user.full_name) > max_name_length:
            max_name_length = len(sync_user.full_name)

    lines = [_('<b>Telegram Bot admins:</b>')]
    for admin in admin_users:
        lines.append(
            '~ TG: {tg_name:>{max_name_length}}'.format(
                tg_name=admin.get_user_link() or admin.full_name,
                max_name_length=max_name_length))

        chat_id = admin.id_.chat_id
        if chat_id != 'sync':
            lines.append('   HO: https://plus.google.com/' + chat_id)

    tg_bot.send_html(msg.chat_id, '\n'.join(lines))


async def command_echo(tg_bot, msg, *args):
    """send back params

    /echo {text}

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return
    if not ensure_args(tg_bot, msg.chat_id, args, at_least=1):
        return
    tg_bot.send_html(msg.chat_id, ' '.join(args))


async def command_leave(tg_bot, msg, *dummys):
    """leave the current chat and perform a cleanup before

    /leave

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        dummys (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    tg_bot.send_html(msg.chat_id, _("I'll be back!"))

    path = ['telesync', 'tg2ho', msg.chat_id]
    if tg_bot.bot.memory.exists(path):
        targets = tg_bot.bot.memory.get_by_path(path).copy()
        # cleanup tg->ho syncs
        await command_clear_sync_ho(tg_bot, msg)
    else:
        targets = tuple()

    # cleanup tg chat data
    tg_bot.bot.memory.pop_by_path(['telesync', 'chat_data', msg.chat_id])

    # cleanup ho -> tg
    ho2tg = tg_bot.bot.memory.get_by_path(['telesync', 'ho2tg'])
    args = ('telesync', 'remove', msg.chat_id)
    for ho_conv_id, tg_chat_ids in ho2tg.copy().items():
        if msg.chat_id in tg_chat_ids:
            event = FakeEvent(ho_conv_id, tg_bot.user, '')
            await command.run(tg_bot.bot, event, *args)

    # pylint:disable=protected-access
    queue = tg_bot._cache_sending_queue.get(msg.chat_id)
    # pylint:enable=protected-access

    await queue.single_stop(5)

    try:
        has_left = await tg_bot.leaveChat(msg.chat_id)
    except telepot.exception.TelegramError:
        logger.exception('leave request for %s failed',
                         msg.chat_id)
    else:
        if has_left:
            # there will be no bot api message for this membership change
            # we need to create it manually
            for conv_id in targets:
                asyncio.ensure_future(tg_bot.bot.sync.membership(
                    identifier='telesync:' + msg.chat_id, conv_id=conv_id,
                    user=msg.user, title=msg.get_group_name(), type_=2,
                    participant_user=[tg_bot.user, ]))
            return

    # pylint:disable=protected-access
    tg_bot._cache_sending_queue.pop(msg.chat_id)  # drop the blocked queue
    # pylint:enable=protected-access

    error = _('Sorry, but I am not able to leave this chat on my own.')
    await tg_bot.send_html(msg.chat_id, error)


async def command_chattitle(tg_bot, msg, *args):
    """change the synced title of the current or given chat

    /chattitle [<chatid>] <title>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    text = tg_bot.bot.call_shared(
        'setchattitle', args=args, platform='telesync',
        fallback=msg.chat_id, source=tg_bot.bot.memory['telesync']['chat_data'])

    tg_bot.send_html(msg.chat_id, text)


def get_chat_name(tg_bot, chat_id):
    """get the cached name of a chat

    Args:
        tg_bot (core.TelegramBot): the running instance
        chat_id (str): telegram chat identifier

    Returns:
        str: the chats title or 'unknown' if no title is cached
    """
    try:
        return tg_bot.bot.memory.get_by_path(
            ['telesync', 'chat_data', chat_id, 'name'])
    except KeyError:
        return _('unknown')


async def command_sync_config(tg_bot, msg, *args):
    """update a config entry for the current or given chat

    /sync_config key value

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    available_chats = tg_bot.bot.memory['telesync']['chat_data']

    if not args or args[0].lower() in ('interactive', 'ia'):
        reply = msg.msg_id

        if (len(args) == 3 and args[1] in available_chats and
                (args[2] in SYNC_CONFIG_KEYS or
                 'sync_' + args[2] in SYNC_CONFIG_KEYS)):
            text = _('You may now copy and paste the next message and edit '
                     'the current value')

            new_msg = await tg_bot.sendMessage(msg.chat_id, text)

            text = '/sync_config %s %s "%s"' % (
                args[1], args[2], get_sync_config_entry(tg_bot.bot,
                                                        'telesync:' + args[1],
                                                        args[2]))

            keyboard = ReplyKeyboardRemove(remove_keyboard=True)
            reply = new_msg.get('message_id', reply)

        elif len(args) > 1 and args[1] in available_chats:
            raw_keyboard = [
                [KeyboardButton(text='/cancel')],
            ]
            raw_keyboard += [
                [KeyboardButton(text=('/sync_config ia %s %s'
                                      % (args[1], key)))]
                for key in SYNC_CONFIG_KEYS
            ]
            keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True,
                selective=True,
                keyboard=raw_keyboard
            )
            text = _('available config entries:')
        else:
            raw_keyboard = [
                [KeyboardButton(text='/cancel')],
            ]
            raw_keyboard += [
                [KeyboardButton(text=('/sync_config ia %s\n(%s)'
                                      % (chat_id,
                                         get_chat_name(tg_bot, chat_id))))]
                for chat_id in sorted(available_chats)
            ]
            keyboard = ReplyKeyboardMarkup(
                resize_keyboard=True,
                selective=True,
                keyboard=raw_keyboard
            )
            text = _('available Telegram Chats:')

        await tg_bot.sendMessage(msg.chat_id, text, reply_markup=keyboard,
                                 reply_to_message_id=reply)
        return

    if len(args) > 1 and args[0] in available_chats:
        chat_id = args[0]
        key = args[1]
        value = ' '.join(args[2:])
    else:
        chat_id = msg.chat_id
        key = args[0]
        value = ' '.join(args[1:])

    conv_id = 'telesync:' + chat_id

    try:
        last_value, new_value = tg_bot.bot.call_shared('sync_config', conv_id,
                                                       key, value)
    except (KeyError, TypeError) as err:
        text = err.args[0]

    else:
        text = _(
            '{sync_option} updated for channel "{tg_id}" from "{old}" to "{new}"'
        ).format(sync_option=key, tg_id=chat_id, old=last_value, new=new_value)

    await tg_bot.sendMessage(
        msg.chat_id, text,
        reply_markup=ReplyKeyboardRemove(remove_keyboard=True))


async def command_restrict_user(tg_bot, msg, *args):
    """limit sending of given message types

    /restrict_user <*ids|'all'> <False|'messages'|'media'|'sticker'|'websites'|
                                 'sticker+websites'>

    Args:
        tg_bot (core.TelegramBot): the running instance
        msg (message.Message): a message wrapper
        args (str): message text tokens
    """
    if not ensure_admin(tg_bot, msg):
        return

    if msg['chat']['type'] != 'supergroup':
        tg_bot.send_html(msg.chat_id,
                         _('This command can be issued in supergroups only'))
        return

    if not args or args[-1].lower() not in RESTRICT_OPTIONS:
        tg_bot.send_html(
            tg_chat_id=msg.chat_id,
            html=_('Check syntax:\n'
                   '/restrict_user <ids | all> <"{options}">'
                   ).format(options='" | "'.join(RESTRICT_OPTIONS))
        )
        return

    chat_users = tg_bot.bot.memory.get_by_path(
        ['telesync', 'chat_data', msg.chat_id, 'user'])

    if args[0].lower() == 'all':
        target_users = tuple(chat_users.copy().keys())
    else:
        for user_id in args[:-1]:
            if user_id not in chat_users:
                tg_bot.send_html(
                    msg.chat_id,
                    _('The user %s is not member of the current chat or has not'
                      ' written anything so far in here.') % user_id)
                return
        target_users = args[:-1]

    mode = args[-1].lower()
    failed = await restrict_users(tg_bot, msg.chat_id, mode, target_users)

    if failed:
        lines = [_('/restrict_users failed for:')]
        for user_id, result in failed.items():
            lines.append('- %s:\n  %s' % (
                (await tg_bot.get_tg_user(user_id)).full_name, repr(result)))

        tg_bot.send_html(msg.chat_id, '\n'.join(lines))
    else:
        tg_bot.send_html(msg.chat_id, _('/restrict_users finished successful'))


async def restrict_users(tg_bot, tg_chat_id, mode, user_ids, silent=False):
    """limit sending of given message types for users

    Args:
        tg_bot (core.TelegramBot): the running instance
        tg_chat_id (str): a Telegram supergroup chat_id
        mode (str): a restrict mode, see `RESTRICT_OPTIONS`
        user_ids (iterable): a set of Telegram `user_id`s (str)
        silent (bool): (optional) set to `True` to disable status messages

    Returns:
        dict: keys are the `user_id`s of users that could not restricted,
         values are `Exception`s raised during the restriction or `False`

    Raises:
        ValueError: the given `mode` is not valid
    """
    if mode not in RESTRICT_OPTIONS:
        raise ValueError('"%s" is not a valid restrict `mode`' % repr(mode))

    # filter the bot users user_id
    user_ids = tuple(set(user_ids) - {tg_bot.user.usr_id})

    rights = (NO_SENDING_RIGHTS if mode == 'messages' else
              NO_MEDIA_RIGHTS if mode == 'media' else
              NO_STICKER_RIGHTS if mode == 'sticker' else
              NO_WEBPREVIEW_RIGHTS if mode == 'websites' else
              NO_WEBPREVIEW_AND_STICKER_RIGHTS if mode == 'sticker+websites'
              else FULL_RIGHTS)

    if not silent:
        status_msg = await tg_bot.sendMessage(
            tg_chat_id,
            _('Processing the queue of /restrict_users for %s users.')
            % len(user_ids))

    results = {}
    for chunk in (user_ids[start:start + 10]
                  for start in range(0, len(user_ids), 10)):
        if not silent:
            await tg_bot.editMessageText(
                (tg_chat_id, status_msg['message_id']),
                _('Finished {completed}/{num_all} requests for /restrict_users'
                  ).format(completed=len(results), num_all=len(user_ids)))

        raw_results = await asyncio.gather(
            *(tg_bot.restrictChatMember(tg_chat_id, user_id, **rights)
              for user_id in chunk),
            return_exceptions=True)

        results.update({user_id: raw_results.pop(0)
                        for user_id in chunk})

    if not silent:
        await tg_bot.deleteMessage((tg_chat_id, status_msg['message_id']))

    failed = {user_id: (result.description
                        if isinstance(result, telepot.exception.TelegramError)
                        else result)
              for user_id, result in results.items()
              if result is not True}
    return failed
