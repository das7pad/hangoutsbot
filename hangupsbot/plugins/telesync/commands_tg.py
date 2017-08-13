"""Telegram-comamnds"""
__author__ = 'das7pad@outlook.com'

import logging

logger = logging.getLogger(__name__)

def ensure_admin(tg_bot, msg):
    """return weather the user is admin, and respond if be_quiet is off

    Args:
        msg: Message instance

    Returns:
        boolean, True if user is Admin, otherwise False
    """
    if not msg.user.usr_id in tg_bot.config('admins'):
        if not tg_bot.config('be_quiet'):
            tg_bot.send_html(msg.chat_id, _('This command is admin-only!'))
        return False
    return True

def ensure_private(tg_bot, msg):
    """return weather the chat is private, and respond if be_quiet is off

    Args:
        msg: Message instance

    Returns:
        boolean, True if chat is of type private, otherwise False
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
        tg_chat_id: int
        args: list of strings
        between: tuple of int, lower/higher limit for the ammount of args
        at_least: int, ammount of args that are required at least

    Returns:
        boolean, True if the number is correct, otherwise False
    """
    if between is None and at_least is None:
        between = (1, 1)
    if ((between is not None and
         len(args) not in range(between[0], between[1]+1)) or
            (at_least is not None and len(args) < at_least)):
        if not tg_bot.config('be_quiet'):
            tg_bot.send_html(tg_chat_id, _('Check arguments.'))
        return False
    return True

async def command_start(tg_bot, msg, *args):
    """answer with the start message and check for deeplinking, private only

    /start [syncprofile]

    Args:
        msg: Message instance
        args: tuple, arguments that were passed after the command
    """
    if ensure_private(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         tg_bot.config('start_message').format(
                             name=msg.user.full_name,
                             botusername=tg_bot.user.username,
                             botname=tg_bot.user.full_name))

    if 'syncprofile' in args:
        await command_sync_profile(tg_bot, msg)

async def command_whoami(tg_bot, msg, *dummys):
    """answer with user_id of request message, private only

    /whereami

    Args:
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
    """
    if ensure_private(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         _("Your Telegram user id is '%s'") % msg.user.usr_id)

async def command_whereami(tg_bot, msg, *dummys):
    """answer with current tg_chat_id, admin only

    /whereami

    Args:
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
    """
    if ensure_admin(tg_bot, msg):
        tg_bot.send_html(msg.chat_id,
                         _("This chat has the id '{}'").format(msg.chat_id))

async def command_set_sync_ho(tg_bot, msg, *args):
    """set sync with given hoid if not already set

    /setsyncho <hangout conv_id>

    Args:
        msg: Message instance
        args: tuple, arguments that were passed after the command
    """
    if not ensure_admin(tg_bot, msg):
        return

    if not ensure_args(tg_bot, msg.chat_id, args):
        return

    bot = tg_bot.bot
    target = args[0]
    lines = []
    tg2ho = bot.memory.get_by_path(['telesync', 'tg2ho'])
    targets = tg2ho.setdefault(msg.chat_id, [])
    if target in targets:
        lines.append(_("TG -> HO: target '{}' already set").format(target))
    else:
        targets.append(target)
        lines.append(_("TG -> HO: target '{}' added".format(target)))

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

    /clearsyncho

    Args:
        msg: Message instance
        args: tuple, arguments that were passed after the command
    """
    bot = tg_bot.bot
    if not ensure_admin(tg_bot, msg):
        return

    path_tg2ho = ['telesync', 'tg2ho']

    lines = []
    tg2ho = bot.memory.get_by_path(path_tg2ho)
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

        if conv_id in ho2tg and msg.chat_id in ho2tg[conv_id]:
            ho2tg[conv_id].remove(msg.chat_id)
            lines.append(_('TG <- HO: chat removed from "%s"') % conv_id)
            if not ho2tg[conv_id]:
                bot.memory.pop_by_path(path_ho2tg + [conv_id])

    if not targets:
        tg2ho.pop(msg.chat_id)

    bot.memory.save()
    text = '\n'.join(lines) or _('No syncs to clear found')

    tg_bot.send_html(msg.chat_id, text)

async def command_add_admin(tg_bot, msg, *args):
    """add admin id to admin list if not present

    /addadmin <tg_user_id>

    Args:
        msg: Message instance
        args: tuple, arguments that were passed after the command
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
        msg: Message instance
        args: tuple, arguments that were passed after the command
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
        msg: Message instance
        args: tuple, arguments that were passed after the command

    Returns:
        boolean, True
    """
    msg.text = '{bot_cmd} tldr {args}'.format(bot_cmd=tg_bot.bot.command_prefix,
                                              args=' '.join(args)).strip()
    if msg.user.id_.chat_id == 'sync':
        # a valid chat_id is required to run commands
        msg.user.id_.chat_id = tg_bot.bot.user_tg_bot()['chat_id']

    # sync the message text to get the tldr
    return True

async def command_sync_profile(tg_bot, msg, *dummys):
    """init profilesync, needs confirmation via pHO

    /syncprofile

    Args:
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
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

    elif bot.memory.exists(base_path + ['pending_2ho', user_id]):
        await tg_bot.profilesync_info(user_id, is_reminder=True)
        return

    bot.sync.start_profile_sync('telesync', user_id)

    await tg_bot.profilesync_info(user_id)

async def command_unsync_profile(tg_bot, msg, *dummys):
    """split tg and ho-profile

    /unsyncprofile

    Args:
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
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
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
    """
    if not ensure_admin(tg_bot, msg):
        return

    tg_bot.send_html(
        msg.chat_id,
        'id: {usr_id}, name: {name}, username: @{username}'.format(
            usr_id=tg_bot.user.usr_id, name=tg_bot.user.first_name,
            username=tg_bot.user.username))

async def command_get_admins(tg_bot, msg, *dummys):
    """send back a formated list of Admins

    /getadmins

    Args:
        msg: Message instance
        *dummys: tuple, arguments that were passed after the command
    """
    admin_users = []
    max_name_length = 0
    for admin_id in tg_bot.config('admins'):
        sync_user = await tg_bot.get_tg_user(user_id=admin_id, gpluslink=True)

        admin_users.append(sync_user)

        # update name length
        if len(sync_user.full_name) > max_name_length:
            max_name_length = len(sync_user.full_name)

    lines = [_('<b>Telegram Botadmins:</b>')]
    for admin in admin_users:
        lines.append(
            '~ TG: {tg_name:>{max_name_length}}'.format(
                tg_name=admin.get_user_link() or admin.full_name,
                max_name_length=max_name_length))

        chat_id = admin.id_.chat_id
        if chat_id != 'sync':
            lines.append('   HO: https://plus.google.com/' + chat_id)

    tg_bot.send_html(msg.chat_id, '\n'.join(lines))
