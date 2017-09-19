"""migration, storage and storage utils for running slackrtms"""
import logging


logger = logging.getLogger(__name__)


SLACKRTMS = []

DEFAULT_CONFIG = {
    'conversations': {
        'slackrtm': {
            # the users name is handled separately
            'sync_format_message': '{reply}{edited}{image_tag}{text}',
            'sync_format_bot': '{reply}{edited}{image_tag}{text}',
        },
    },
    'slackrtm': [],
}

DEFAULT_MEMORY = {
    'slackrtm': {},
}


def slackrtm_conversations_set(bot, team_name, synced_hangouts):
    bot.memory.set_by_path(["slackrtm", team_name, "synced_conversations"],
                           synced_hangouts)
    bot.memory.save()

def slackrtm_conversations_get(bot, team_name):
    full_path = ["slackrtm", team_name, "synced_conversations"]
    if bot.memory.exists(full_path):
        return bot.memory.get_by_path(full_path)
    return []

def setup_storage(bot):
    """set defaults and run migration

    Args:
        bot: HangupsBot instance
    """
    bot.config.set_defaults(DEFAULT_CONFIG)
    bot.memory.set_defaults(DEFAULT_MEMORY)
    _migrate_data(bot)

def _migrate_data(bot):
    """run all migration steps

    Args:
        bot: HangupsBot instance
    """
    _migrate_20170319(bot)
    _migrate_20170917(bot)
    _migrate_20170919(bot)

    bot.config.save()
    bot.memory.save()

def _migrate_20170319(bot):
    """unbreak slackrtm memory.json usage

    previously, this plugin abused 'user_data' to store its internal team config

    Args:
        bot: HangupsBot instance
    """
    memory_root_key = "slackrtm"
    if bot.memory.exists([memory_root_key]):
        return

    configurations = bot.get_config_option('slackrtm')
    migrated_configurations = {}
    for configuration in configurations:
        team_name = configuration["name"]
        broken_path = ['user_data', team_name]
        if bot.memory.exists(broken_path):
            legacy_team_memory = bot.memory.get_by_path(broken_path).copy()
            migrated_configurations[team_name] = legacy_team_memory

    bot.memory.set_by_path([memory_root_key], migrated_configurations)

def _migrate_20170917(bot):
    """migrate the synced profiles

    Args:
        bot (hangupsbot.HangupsBot): the running instance
    """
    for team, data in bot.memory.get_option('slackrtm').items():
        if data.get('_migrated_', 0) >= 20170917:
            continue
        data['_migrated_'] = 20170917
        if 'identities' not in data:
            return

        identifier = 'slackrtm:' + team
        identities = data['identities']
        if 'slack' in identities:
            path_2ho = ['profilesync', identifier, '2ho']
            bot.memory.set_by_path(path_2ho, identities['slack'])
        if 'hangouts' in identities:
            path_ho2 = ['profilesync', identifier, 'ho2']
            bot.memory.set_by_path(path_ho2, identities['hangouts'])

def _migrate_20170919(bot):
    """extract the config entries for sync behaviour

    Args:
        bot (hangupsbot.HangupsBot): the running instance
    """
    for team, data in bot.memory.get_option('slackrtm').items():
        if data.get('_migrated_', 0) >= 20170919:
            continue
        data['_migrated_'] = 20170919
        identifier = 'slackrtm:' + team
        for sync in data['synced_conversations']:
            channel_tag = identifier + ':' + sync['channelid']
            path = ['conversations', channel_tag]

            do_not_show_nicknames = sync.get('showhorealnames')
            if do_not_show_nicknames is not None:
                # do_not_show_nicknames may store `real`, `nick` or `both`
                bot.config.set_by_path(path + ['sync_nicknames'],
                                       do_not_show_nicknames != 'real')

            channel_title = sync.get('slacktag')
            if isinstance(channel_title, str):
                title_path = ['chattitle', channel_tag]
                bot.memory.set_by_path(title_path, channel_title)

            sync_joins = sync.get('sync_joins')
            if sync_joins is not None:
                for key in ('sync_membership_join', 'sync_membership_leave'):
                    bot.config.set_by_path(path + [key], sync_joins)
