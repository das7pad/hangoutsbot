"""simple way to sync cross-platform messages, membership and renames"""
__author__ = 'das7pad@outlook.com'

import functools

from commands import Help # pylint: disable=wrong-import-order
import plugins

DEFAULT_CONFIG = {

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

    # gifs and videos processing consumes a lot of CPU-Time, even if no resize
    # is needed in any chat room. The processing is detached and could run on
    # multiple CPU-Cores. This config entry sets a limit for all chats on the
    # input-file-size of videos and gifs.
    # Media with a size above this limit will be forwarded 1:1. Unit is KB
    "sync_process_animated_max_size": 4096,

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
}

# exclude those from beeing changed without effect by sync_config()
GLOBAL_KEYS = ('sync_cache_dump_image', 'sync_cache_timeout_conv_user',
               'sync_cache_timeout_gif', 'sync_cache_timeout_photo',
               'sync_cache_timeout_sending_queue', 'sync_cache_timeout_sticker',
               'sync_cache_timeout_video', 'sync_separator')

SYNC_CONFIG_KEYS = tuple(sorted(set(DEFAULT_CONFIG.keys()) - set(GLOBAL_KEYS)))

HELP = {
    'chattitle': _('Update the synced title for a conversation, specify a '
                   'conversation identifer to update the tag of another '
                   'conversation.\n{bot_cmd} chattitle [<conv id>] <new title>'
                   '\nFormat the new title\n"shot version", "long version"\nto '
                   'get a shot title sent with the message and have a different'
                   ' one sent with @mentions/etc.\n'
                   'The example <i>{bot_cmd} chattitle "touri", "Tourists '
                   'Berlin"</i> might result in a message on another platform '
                   'that looks like\nBob (touri) : @alice where do I find X?\n'
                   'Bob (touri) @mentioned you in "Berlin Tourists":\n'
                   '@alice where do I find X?'),

    # needs to be updated as more profilesyncs are registered during plugin load
    'sync_profile': '',

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
    plugins.register_user_command(['syncprofile'])
    plugins.register_admin_command(['chattitle'])
    plugins.register_help(HELP)

    bot.register_shared('setchattitle', functools.partial(_chattitle, bot))

async def chattitle(bot, event, *args):
    """set the title that will be synced for the current conversation

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tupel
    """
    return _chattitle(bot, args, 'hangouts', bot.conversations, event.conv_id)

def _chattitle(bot, args=None, platform=None, source=None, fallback=None):
    """update or receive the chattitle for a given conversation on any platform

    allowed args ([<conv_id>], <new title>)

    Args:
        bot: HangupsBot instance
        args: additional text as tupel
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


async def syncprofile(bot, event, *args):
    """syncs ho-user with platform-user-profile and syncs pHO <-> platform 1on1

    ! syncprofile <token>
    ! syncprofile <token> split
    token is generated on the other platforms

    Args:
        bot: HangupsBot instance
        event: hangups event instance
        args: additional text as tupel
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
