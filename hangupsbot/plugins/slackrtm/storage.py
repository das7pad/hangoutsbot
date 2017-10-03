"""migration, storage and storage utils for running slackrtms"""
import logging


logger = logging.getLogger(__name__)


SLACKRTMS = []

LAST_MIGRATION = 20170919

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

DEFAULT_TEAM_MEMORY = {
    'synced_conversations': [],
    '_migrated_': LAST_MIGRATION,
}


def setup_storage(bot):
    """set defaults and run migration

    Args:
        bot (hangupsbot.HangupsBot): the running instance
    """
    bot.config.set_defaults(DEFAULT_CONFIG)
    bot.memory.set_defaults(DEFAULT_MEMORY)
    _migrate_data(bot)

def migrate_on_domain_change(slackrtm, old_domain):
    """migrate the team data in memory

    Args:
        slackrtm (core.SlackRTM): a running instance
        old_domain (str): recent slackdomain of the team
    """
    new_domain = slackrtm.slack_domain
    # cover a missing `domain` entry in slackrtm.config
    old_domain = slackrtm.name if old_domain is None else old_domain

    if old_domain == new_domain:
        return

    bot = slackrtm.bot
    new_path = ['slackrtm', new_domain]

    if bot.memory.exists(new_path):
        logger.warning('Cancelled migration from domain %(old)s to %(new)s as '
                       'there is already data present for the domain %(new)s',
                       dict(old=repr(old_domain), new=repr(new_domain)))
        return
    logger.info('Migrating data from domain %s to %s',
                repr(old_domain), repr(new_domain))

    old_path = ['slackrtm', old_domain]

    if bot.memory.exists(old_path):
        data = bot.memory.pop_by_path(old_path)
    else:
        # first run
        data = DEFAULT_TEAM_MEMORY.copy()

    bot.memory.set_by_path(new_path, data)

    # migrate per conversation/per-slackrtm config and memory
    old_identifier = 'slackrtm:' + old_domain
    new_identifier = 'slackrtm:' + new_domain

    per_chat_data = (
        bot.config['conversations'],
        bot.memory['chattitle'],
        bot.memory['profilesync'],
    )
    for data in per_chat_data:
        for identifier in data.copy():
            if (old_identifier not in identifier
                    or not identifier.startswith('slackrtm:')):
                continue
            # covers `slackrtm:<team>` and `slackrtm:<team>:<channel>`
            new_conv_id = identifier.replace(old_identifier, new_identifier)
            data[new_conv_id] = data.pop(identifier)

    # migrate pending profilesyns
    pending_profilesyncs = bot.memory['profilesync']['_pending_']
    for token, platform in pending_profilesyncs.items():
        if platform == old_identifier:
            pending_profilesyncs[token] = new_identifier

    bot.config.save()
    bot.memory.save()

def _migrate_data(bot):
    """run all migration steps

    Args:
        bot (hangupsbot.HangupsBot): the running instance
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
        bot (hangupsbot.HangupsBot): the running instance
    """
    memory_root_key = 'slackrtm'
    if bot.memory.exists([memory_root_key]):
        return

    configurations = bot.get_config_option('slackrtm')
    migrated_configurations = {}
    for configuration in configurations:
        team_name = configuration['name']
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
