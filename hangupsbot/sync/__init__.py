"""simple way to sync cross-platform messages, membership and renames"""
__author__ = 'das7pad@outlook.com'

import functools

from hangups import hangouts_pb2

from commands import Help # pylint: disable=wrong-import-order
import plugins

from .user import SyncUser
from .utils import get_sync_config_entry


DEFAULT_CONFIG = {
    # store conv_ids for conversations that have auto kick enabled
    'autokick': [],

    # used separate the meta info from the actual text of a message
    'sync_separator': ' : ',

    # decorator for a synced messages
    'sync_tag_edited': _('<b>Edit:</b>\n'),
    'sync_tag_gif': _('[Gif]'),
    'sync_tag_photo': _('[Photo]'),
    'sync_tag_sticker': _('[Sticker]'),
    'sync_tag_video': _('[Video]'),

    # caching:
    # timeouts for caching: images, gifs, videos 48h, sticker ~ 1month,
    #                       user lists 10minutes, sending queues 6h
    'sync_cache_timeout_photo': 172800,
    'sync_cache_timeout_gif': 172800,
    'sync_cache_timeout_video': 172800,
    'sync_cache_timeout_sticker': 2500000,
    'sync_cache_timeout_conv_user': 600,
    'sync_cache_timeout_sending_queue': 21600,
    # dump to memory: every 6h
    'sync_cache_dump_image': 21600,

    # gifs and videos processing consumes a lot of CPU-Time, even if no resize
    # is needed in any chat room. The processing is detached and could run on
    # multiple CPU-Cores. This config entry sets a limit for all chats on the
    # input-file-size of videos and gifs.
    # Media with a size above this limit will be forwarded 1:1. Unit is KB
    "sync_process_animated_max_size": 4096,

    ############################################################################
    # the next entrys are set global, to be then able to set them also per conv
    # as access is similar to bot.get_config_suboption(conv_id, key)

    'sync_nicknames': True,

    # available keys: firstname, fullname, nickname
    # if the user has no nickname or none should be synced, ..._only is used
    'sync_format_name': '{firstname} ({nickname})',
    'sync_format_name_only': '{fullname}',

    'sync_title' : False,

    # toggle to use the live title of the conv instead of the custom chattitle
    'sync_title_long': False,

    'sync_membership_join': True,
    'sync_membership_leave': True,

    # available keys: name, text, title, separator, reply, edited, image_tag
    # activate 'sync_title' to use the title key
    'sync_format_message': ('{reply}{edited}<b>{name}</b>{title}{separator}'
                            '{image_tag}{text}'),
    # a message sent as the bot user
    'sync_format_message_bot': '{reply}{edited}{image_tag}{text}',

    'sync_format_membership_add': _('<b>{name}</b> added {participants} {title}'
                                   ),
    'sync_format_membership_kick': _('<b>{name}</b> kicked {participants} '
                                     '{title}'),
    'sync_format_membership_join': _('<b>{name}</b> joined {title}'),
    'sync_format_membership_leave': _('<b>{name}</b> left {title}'),

    # available key: title
    'sync_format_title': ' <b>({title})</b>',
    'sync_format_title_membership_add': 'to <b>{title}</b>',
    'sync_format_title_membership_kick': 'from <b>{title}</b>',
    'sync_format_title_membership_join': '<b>{title}</b>',
    'sync_format_title_membership_leave': '<b>{title}</b>',

    # sync a certain media type at all
    'sync_photo': True,
    'sync_gif': True,
    'sync_sticker': True,
    'sync_video': True,

    # sync a certain media type appearing in a reply, size can be changed below
    'sync_reply_photo': True,
    'sync_reply_gif': True,
    'sync_reply_sticker': True,
    'sync_reply_video': True,

    # photos can not be edited, but might be needed for the context of the
    #  photo caption
    'sync_photo_on_edit': True,
    'sync_gif_on_edit': True,
    'sync_sticker_on_edit': True,
    'sync_video_on_edit': True,

    # size in px, or set to 0 to disable resizing
    # resizing of videos and gifs needs CPU-Power/takes some time
    'sync_size_photo': 0,
    'sync_size_gif': 512,
    'sync_size_sticker': 128,
    'sync_size_video': 0,

    # attach smaller media if the reply contains one
    'sync_reply_size_photo': 128,
    'sync_reply_size_gif': 64,
    'sync_reply_size_sticker': 64,
    'sync_reply_size_video': 128,

    # sync a connected reply message
    'sync_reply': True,
    # after n char cut and add '...'
    'sync_reply_limit': 50,
    # do not relay a replys text if less then x messages passed since the
    #  original message was sent
    'sync_reply_spam_offset': 10,

    # available keys: name, text
    'sync_format_reply': ('| <i><b>{name}</b>:</i>\n| <i>{image_tag}{text}</i>'
                          '\n'),
    'sync_format_reply_empty': '| <i><b>{name}</b>: {image_tag}~</i>\n',
    'sync_format_reply_bot': '| <i>{image_tag}{text}</i>\n',
    'sync_format_reply_bot_empty': '| <i>{image_tag}~</i>\n',
}

DEFAULT_MEMORY = {
    'chattitle': {},
    'check_users': {}
}

# exclude those from beeing changed without effect by sync_config()
GLOBAL_KEYS = ('sync_cache_dump_image', 'sync_cache_timeout_conv_user',
               'sync_cache_timeout_gif', 'sync_cache_timeout_photo',
               'sync_cache_timeout_sending_queue', 'sync_cache_timeout_sticker',
               'sync_cache_timeout_video', 'sync_separator', 'autokick',
               'sync_process_animated_max_size')

SYNC_CONFIG_KEYS = tuple(sorted(set(DEFAULT_CONFIG.keys()) - set(GLOBAL_KEYS)))

HELP = {
    'autokick': _('Enable or disable auto kick for the current or given '
                  'conversation. This requires a configured user list, see '
                  '<b>{bot_cmd} help check_users</b>. New users joining the '
                  'specified conversation - or a sync-target of it - are kicked'
                  ' automatically if they were not added to the '
                  '<i>check_users</i> -userlist before.\n'
                  'Usage:\n{bot_cmd} autokick <conv_id | alias>\n'
                  'inverts the current setting'),

    'chattitle': _('Update the synced title for a conversation, specify a '
                   'conversation identifer to update the tag of another '
                   'conversation.\n{bot_cmd} chattitle [<conv id>] <new title>'
                   '\nThe custom chattitle will be sent with a message from the'
                   ' specified conversation\n'
                   'The example <i>{bot_cmd} chattitle "touri"</i> might result'
                   ' in a message on another platform that looks like\n'
                   '\'<b>Bob (touri) :</b> @alice where do I find X?\'\n'
                   'and the @mention message for "alice" will get the <i>live '
                   '</i>-title:\n\'Bob @mentioned you in "Berlin Tourists":\n'
                   '@alice where do I find X?\''),

    'syncusers': _('<b>Usage:</b>\n{bot_cmd} syncusers [<conv_id>] [flat] '
                   '[unique] [profilesync]\nAll arguments are optional, use\n '
                   '<i>flat</i>  to get all users in one list\n <i>unique</i> '
                   'to remove duplicates, use it with flat\n <i>profilesync</i>'
                   '  to include only users with a synced G+ profile\n\n'
                   '{bot_cmd} syncusers flat unique\n{bot_cmd} syncusers '
                   'profilesync'),

    # needs to be updated as more profilesyncs are registered during plugin load
    'sync_profile': '',

    'sync1to1': _('Change the sync-setting for the private Hangout with the bot'
                  ' and the private-chat on another platform:\n'
                  '{bot_cmd} sync1to1 <platform> [off]'),

    'check_users': _('Perform a platform wide member check on the current or '
                     'given conversation. Users will be automatcally kicked or'
                     ' added, profilesyncs are used to identify users on other '
                     'platforms. Usage:\n{bot_cmd} check_users [<conv id>] '
                     '[<G+ user ids, 21 digits each>] [kick_only] '
                     '[<add | remove>]\n"kick_only" does not add missing users'
                     'to the Hangout, edit an existing user list by adding '
                     '"add" or "remove" to the command\n'
                     'Note: The Bot needs kick-permissions: in Hangouts: not '
                     'joined via invite-url; Telegram: chat setting may not be '
                     '"all users are admins"\nAdmins on each platform and the '
                     'bot user are whitelisted on each platform.\nExamples ~ '
                     'explaination:\n{bot_cmd} check_users\n~ check current '
                     'conv with the last userlist or kick everyone\n{bot_cmd} '
                     'check_users UgyiJIGTDLfz6d5cLVp4AaABAQ '
                     '012345678910111213141 123456789101112131415 kick_only\n'
                     '~ reset the user list of "UgyiJIGTDLfz6d5cLVp4AaABAQ" to '
                     'the two specified G+IDs and check all relays of the given'
                     ' conv_id weather users not matching these two user IDs '
                     'are attending and kick those'),

    'sync_config': _('Change a per conversation config entry for the current '
                     'conversation, another Hangouts conversation or a platform'
                     ' chat that has initialised by the other platform:\n'
                     '{bot_cmd} sync_config [<conv identifer>] key <new value>'
                     '\nTo get list of available conv identifier, use\n'
                     '{bot_cmd} sync_config list\nThis list does not include '
                     'regular Hangouts conv ids as these can be received via\n'
                     '{bot_cmd} hangouts [<search term>]'),

}

SYNCPROFILE_HELP = _(
    'A profile sync connects your G+Profile to other platforms, like that you '
    'can use the bot commands and all other plugins of the bot as if you are on'
    ' Hangouts and send from there. In addition synced messages can be posted '
    'with your G+ Name, and the configured custom nickname from <b>{bot_cmd} '
    'setnickname</b>. Unlease that power and start from your platform of choice'
    ' with\n{platform_cmds}\n\nIf the platform provides syncing of private '
    'chats and <i>split</i>  is not sent with your token, my private messages '
    'like mentions/subscribes/... will appear on the other platform as well.\n'
    'Examples:\n{bot_cmd} syncprofile DEMO123\n{bot_cmd} syncprofile 123DEMO '
    'split')


def _initialise(bot):
    """register commands and ensure an existing target for hangouts chattitles

    Args:
        bot: HangupsBot instance
    """
    bot.memory.validate(DEFAULT_MEMORY)
    plugins.register_user_command(['syncusers', 'syncprofile', 'sync1to1'])
    plugins.register_admin_command(['chattitle', 'sync_config', 'check_users',
                                    'autokick'])
    plugins.register_sync_handler(_autokick, 'membership')
    plugins.register_help(HELP)

    bot.register_shared('syncusers', functools.partial(_syncusers, bot))

    bot.register_shared('check_users',
                        functools.partial(_config_check_users, bot))

    bot.register_shared('setchattitle', functools.partial(_chattitle, bot))
    bot.register_shared('sync_config', functools.partial(_sync_config, bot))

def _convid_from_args(bot, args, conv_id=None):
    """get the conv_id and cleaned params from raw args

    Args:
        bot: HangupsBot instance
        args: iterable, having strings as items
        conv_id: string, fallback if no other conv_id is in the args specified

    Returns:
        tuple: conv_id or None and the params without conv_id(s)/aliases
    """
    params = []
    for item in args:
        if item in bot.conversations:
            conv_id = item
        elif item in bot.memory['hoalias']:
            conv_id = bot.memory['hoalias'][item]
        else:
            params.append(item)
    return conv_id, params

async def sync_config(bot, event, *args):
    """update a config entry for a conversation

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, a tuple of strings that were passed to the command

    Returns:
        string, the reply of the command or None if the help entry was called
    """
    if not args or (len(args) == 1 and args[0].lower() != 'list'):
        raise Help()

    if args[0].lower() == 'list':
        lines = []
        lines.append(_('Platform specific conversations for sync_config:'))
        lines.extend(sorted([conv for conv in bot.config['conversations']
                             if ':' in conv]))
        return '\n'.join(lines)

    if args[0] in bot.conversations or args[0] in bot.config['conversations']:
        conv_id = args[0]
        key = args[1]
        value = ' '.join(args[2:])
    else:
        conv_id = event.conv_id
        key = args[0]
        value = ' '.join(args[1:])

    try:
        last_value, new_value = _sync_config(bot, conv_id, key, value)
    except (KeyError, TypeError) as err:
        return err.args[0]
    else:
        return _('%s updated for conversation "%s" from "%s" to "%s"') % (
            key, conv_id, last_value, new_value)

def _sync_config(bot, conversation, key, value):
    """update a config entry for a conversation

    Args:
        bot: HangupsBot instance
        conversation: string, conversation identifer to update the config for
        key: string, config key to set a different value on conversation level
        value: any type, the new value

    Returns:
        tuple: the recent value of the config entry and the parsed new value

    Raises:
        KeyError: the config entry is unknown/not allowed per conversation
        TypeError: the new values type does not match with the existing
    """
    if key[:5] != 'sync_':
        key = 'sync_' + key

    if key not in SYNC_CONFIG_KEYS:
        raise KeyError(_('%s is not a valid per conversation config key') % key)
    last_value = get_sync_config_entry(bot, conversation, key)

    if value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]

    new_value = (None if value.lower() == _('none') else
                 True if value.lower() == _('true') else
                 False if value.lower() == _('false') else
                 int(value) if value.isdigit() else value)

    path = ['conversations', conversation, key]

    if new_value is None:
        # reset to default
        bot.config.ensure_path(path)
        bot.config.get_by_path(path[:-1]).pop(key, None)
        new_value = get_sync_config_entry(bot, conversation, key)

    else:
        # verify type and set the new value
        expected_type = type(DEFAULT_CONFIG[key])
        if not isinstance(new_value, expected_type):
            raise TypeError(
                _('%s is not a valid value for %s: expected %s but got %s' % (
                    new_value, key, expected_type, type(new_value))))

        bot.config.set_by_path(path, new_value)

    bot.config.save()
    return last_value, new_value

async def chattitle(bot, event, *args):
    """set the title that will be synced for the current conversation

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tuple
    """
    return _chattitle(bot, args, 'hangouts', bot.conversations, event.conv_id)

def _chattitle(bot, args=None, platform=None, source=None, fallback=None):
    """update or receive the chattitle for a given conversation on any platform

    allowed args ([<conv_id>], <new title>)

    Args:
        bot: HangupsBot instance
        args: additional text as tuple
        platform: string, platform identifier
        source: iterable, used to check if the first arg is set to a valid
            conversation identifer on the given platform
        fallback: string, conversation identifer if no other is specified in the
            args

    Returns:
        string, if no args besides a conv_id were given, return a text with the
        current title, otherwise return a text with the conv_id, old/new title
    """
    if args and args[0] in source:
        conv_id = args[0]
        args = tuple(args[1:])
    else:
        conv_id = fallback

    path = ['chattitle', platform + ':' + conv_id]
    if bot.memory.exists(path):
        current_title = bot.memory.get_by_path(path)
    else:
        current_title = None

    if not args:
        return _('The current chattitle for {} is "{}".').format(conv_id,
                                                                 current_title)

    new_title = ' '.join(args)
    new_title = '' if new_title == '""' or new_title == "''" else new_title

    bot.memory.set_by_path(path, new_title)
    bot.memory.save()
    return _('Chattitle changed for {} from "{}" to "{}".').format(
        conv_id, current_title, new_title)

async def syncusers(bot, event, *args):
    """get users that attend current or given conversation

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tuple
    """
    return await _syncusers(bot, args, event.conv_id, event.user_id)

async def _syncusers(bot, args, conv_id=None, user_id=None):
    """get users that attend current or given conversation

    non-admins can only get the members of attending conversations

    Args:
        bot: HangupsBot instance
        args: tuple of string, additional words passed to the command
        conv_id: string, fallback if no conversation is specified in the args
        user_id: hangups.user.UserID instance, the user who sent the request
    """
    if 'help' in args:
        raise Help()

    parsed = {key: key in args
              for key in ('flat', 'unique', 'profilesync', 'nolinks', 'ids')}

    conv_id = _convid_from_args(bot, args, conv_id)[0]

    if parsed['ids']:
        parsed['profilesync'] = True
        parsed['unique'] = True
        parsed['nolinks'] = True

    users = await bot.sync.get_users_in_conversation(
        conv_id, return_flat=parsed['flat'], unique_users=parsed['unique'],
        profilesync_only=parsed['profilesync'])

    lines = []
    if parsed['flat']:
        header_template = _('    <b>All platforms merged</b>:')
        conversations = {conv_id: {'all': users}}
    else:
        header_template = '    <b>{identifier}</b>: {count}'
        lines.append(_('Users are listed per platform.'))
        lines.append('')
        conversations = users

    user_count = 0
    for conv_id_, platforms in conversations.items():
        lines.append(_('~ in <i>{title}</i> :').format(
            title=bot.conversations.get_name(conv_id_, conv_id_)))
        for platform, users in platforms.items():
            lines.append(header_template.format(identifier=platform,
                                                count=len(users)))

            for user in users:
                user_id = None if user.id_ == user_id else user_id
                user_count += 1
                if parsed['ids']:
                    label = user.id_.chat_id
                else:
                    label = '<b>%s</b>' % user.get_displayname(conv_id,
                                                               text_only=True)


                lines.append('{spacer} {gplustag}{label}'.format(
                    spacer=' '*6,
                    # do not show a G+ tag if the (G+)userlink is shown anyways
                    gplustag='' if (user.id_.chat_id == 'sync' or parsed['ids']
                                    or not parsed['nolinks']) else '<b>G+ </b>',
                    label=label))

                if parsed['nolinks'] or user.user_link is None:
                    continue

                # (first) userlink
                lines.append('{}{}'.format(' '*9, user.user_link))

                if (user.id_.chat_id != 'sync' and
                        user.id_.chat_id not in user.user_link):
                    # G+ user has got a platform specific link, append a G+ link
                    lines.append('{}https://plus.google.com/{}'.format(
                        ' '*9, user.id_.chat_id))

    if user_id is not None and user_id.chat_id not in bot.config['admins']:
        return _('You are not member of the chat "%s"') % conv_id

    lines.append('')
    lines.append(_('{} users in total.').format(user_count))

    return '\n'.join(lines)

async def syncprofile(bot, event, *args):
    """syncs ho-user with platform-user-profile and syncs pHO <-> platform 1on1

    ! syncprofile <token>
    ! syncprofile <token> split
    token is generated on the other platforms

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tuple
    """
    if not args or (len(args) > 1 and args[1].lower() != 'split'):
        raise Help()

    if not bot.sync.profilesync_cmds:
        return _('There are no platform-syncs available!')

    token = args[0]
    platform = bot.memory['profilesync']['_pending_'].pop(token, None)
    if platform is None:
        lines = [_('Check spelling or start the sync from the platform of your '
                   'choice:')]
        for label, cmd in bot.sync.profilesync_cmds.values():
            lines.append('~ in <b>{}</b> use {}'.format(label, cmd))
        return '\n'.join(lines)

    chat_id = event.user_id.chat_id
    split = args[-1].lower() == 'split'

    conv_1on1 = (await bot.get_1to1(chat_id, force=True)).id_

    base_path = ['profilesync', platform]

    # cleanup
    user_id = bot.memory.pop_by_path(base_path + ['pending_ho2', token])
    bot.memory.pop_by_path(base_path + ['pending_2ho', user_id])

    # profile sync
    bot.memory.set_by_path(base_path + ['2ho', user_id], chat_id)
    bot.memory.set_by_path(base_path + ['ho2', chat_id], user_id)
    bot.memory.save()

    await bot.sync.run_pluggable_omnibus('profilesync', bot, platform, user_id,
                                         conv_1on1, split)

async def sync1to1(bot, event, *args):
    """change the setting for 1on1 syncing to a platform

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent
        args: tuple of strings, additional words passed to the command

    Returns:
        string
    """
    if not args:
        raise Help(_('specify a platform'))

    user_platform = args[0].lower()
    platforms = {}
    matching = []
    for platform, value in bot.sync.profilesync_cmds.copy().items():
        if (user_platform in platform.lower()
                or user_platform in str(value).lower()):
            matching.append(platform)
        platforms[platform.lower()] = platform
        platforms[value[0].lower()] = platform

    if not platforms:
        return _('There are no platform-syncs available!')

    platform = (platforms.get(user_platform)
                or matching[0] if len(matching) == 1 else None)

    if platform is None:
        raise Help(_('"%s" is not a valid sync platform, choose one of:\n%s')
                   % (args[0], '"%s"' % '", "'.join(platforms)))

    chat_id = event.user_id.chat_id
    path = ['profilesync', platform, 'ho2', chat_id]
    if not bot.memory.exists(path):
        label, cmd = bot.sync.profilesync_cmds[platform]
        return _('You do not have a profilesync set for <b>%s</b>!\n'
                 'Start one there with <b>%s</b>') % (label, cmd)
    platform_id = bot.memory.get_by_path(path)

    conv_1to1 = (await bot.get_1to1(chat_id, force=True)).id_

    split = args[-1].lower() == _('off')
    await bot.sync.run_pluggable_omnibus('profilesync', bot, platform,
                                         platform_id, conv_1to1, split)

async def check_users(bot, event, *args):
    """add or kick all users that are missing or not on the list, include syncs

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, additional words passed with the command
    """
    return await _config_check_users(bot, *args, conv_id=event.conv_id)

async def _config_check_users(bot, *args, conv_id=None, targets=None):
    """add or kick all users that are missing or not on the list, include syncs

    Args:
        bot: HangupsBot instance
        args: tuple, additional words passed with the command
        conv_id: string, default conversation if none specified in the args
        targets: list of strings, conversation identifier of relay targets

    Returns:
        string, the command output
    """
    conv_id_, params = _convid_from_args(bot, args)
    if conv_id_ is not None:
        conv_id = conv_id_
        targets = None

    edit = any(key in args for key in ('add', 'remove', 'show'))
    load = edit or not params or (len(params) == 1 and
                                  params[0] in ('kick_only', 'verbose'))

    allowed_users = (set(bot.memory['check_users'][conv_id])
                     if load and conv_id in bot.memory['check_users']
                     else set())

    for item in args:
        if item.isdigit() and len(item) == 21:
            if 'remove' in args:
                allowed_users.discard(item)
            else:
                allowed_users.add(item)

    if allowed_users or edit:
        # sort the ids to get the 'same' list if no changes were made
        bot.memory['check_users'][conv_id] = list(sorted(allowed_users))
        bot.memory.save()
    elif not load:
        return _('specify at least one G+ID to perform a user check')

    if edit:
        lines = [_('allowed users in %s:') % conv_id]
        lines.extend(['%s (%s)' % (chat_id,
                                   SyncUser(bot, user_id=chat_id)
                                   .get_displayname(conv_id, text_only=True))
                      for chat_id in allowed_users])
        lines.append(_('%s users in total' % len(allowed_users)))

        return '\n'.join(lines)

    return await _check_users(bot, conv_id, kick_only='kick_only' in args,
                              verbose='verbose' in args, targets=targets)

async def _check_users(bot, conv_id, kick_only=False, verbose=True,
                       targets=None):
    """add or kick all users that are missing or not on the list, include syncs

    Args:
        bot: HangupsBot instance
        conv_id: string, conversation identifier
        kick_only: boolean, toggle to ignore missing/left users
        verbose: boolean, toggle to get whitelisted users in the output
        targets: list of strings, conversation identifier of relay targets

    Returns:
        string, the command output
    """
    if not targets:
        targets = bot.sync.get_synced_conversations(conv_id=conv_id,
                                                    include_source_id=True)

    allowed_users = set()
    for item in targets:
        if item not in bot.memory['check_users']:
            continue
        allowed_users.update(bot.memory['check_users'][item])

    users = await bot.sync.get_users_in_conversation(conv_id,
                                                     unique_users=False)

    kicked = []
    # kick sequentially to lower the possibility of getting ratelimited
    for user in users:
        if user.id_.chat_id in allowed_users:
            continue
        kicked.append((user, await bot.sync.kick(user=user, conv_id=conv_id)))

    summery = []
    for user, results in kicked:
        results.discard(None)
        status = _('failed')
        if len(results) == 1:
            result = results.pop()

            if result == 'whitelisted' and not verbose:
                continue

            status = (status if result is False else
                      _('success') if result is True else
                      _('whitelisted') if result == 'whitelisted' else
                      str(result))

        summery.append(' '*2 + status)
        summery.append(' '*4 + user.get_displayname(conv_id, True))
        summery.append(' '*4 + user.user_link)
    if summery:
        summery.insert(0, _('Kick requests:'))

    new_user = allowed_users - set([user.id_.chat_id for user in users])

    if new_user and not kick_only:
        await bot.add_user(
            hangouts_pb2.AddUserRequest(
                request_header=bot.get_request_header(),
                invitee_id=[hangouts_pb2.InviteeID(gaia_id=chat_id)
                            for chat_id in new_user],
                event_request_header=hangouts_pb2.EventRequestHeader(
                    conversation_id=hangouts_pb2.ConversationId(id=conv_id),
                    client_generated_id=bot.get_client_generated_id())))

        summery.append(_('Users added:'))
        for item in new_user:
            user = SyncUser(bot, user_id=item)
            summery.append(' '*3 + user.get_displayname(conv_id, True))
            summery.append(' '*3 + user.user_link)

    if not summery:
        summery = [_('No changes')]

    return '\n'.join(summery)

async def _autokick(bot, event):
    """kick users that are not previously whitelisted for the conversation

    Args:
        bot: HangupsBot instance
        event: sync.event.SyncEventMembership instance
    """
    if event.type_ != 1:
        # a user left the conversation
        return

    if (event.conv_id not in bot.config['autokick'] or
            event.conv_id not in bot.memory['check_users']):
        return

    text = await _check_users(bot, event.conv_id, kick_only=True, verbose=False,
                              targets=event.targets)

    if '\n' not in text:
        # no changes
        return

    await bot.coro_send_message(event.conv_id, text)

def autokick(bot, event, *args):
    """change the setting for autokick for a given or the current conversation

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tuple

    Returns:
        string
    """
    conv_id = _convid_from_args(bot, args, conv_id=event.conv_id)[0]

    was_enabled = conv_id in bot.config['autokick']

    if was_enabled:
        bot.config['autokick'].remove(conv_id)
    else:
        bot.config['autokick'].append(conv_id)

    # the first run of autokick will fetch the list from config.defaults and
    # this list then needs to be copied to the 'real' config
    bot.config['autokick'] = bot.config['autokick']

    bot.config.save()

    return _('autokick is %s for %s') % (_('OFF') if was_enabled else _('ON'),
                                         conv_id)
