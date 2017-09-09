"""migration, storage and storage utils for running slackrtms"""
import logging


logger = logging.getLogger(__name__)


SLACKRTMS = []

DEFAULT_CONFIG = {
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
