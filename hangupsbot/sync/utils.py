"""sync utils"""
__author__ = 'das7pad@outlook.com'


def get_sync_config_entry(bot, conv_id, key):
    """get a config entry and search for the value on multiple levels

    conv_id='slackrtm:teamname:C001'
    'slackrtm:teamname:C001' -> 'slackrtm:teamname' -> 'slackrtm' -> global

    Args:
        bot (hangupsbot.HangupsBot): the running instance
        conv_id (str): chat conversation identifier
        key (str): sync config item

    Returns:
        mixed: check sync.DEFAULT_CONFIG for the expected type
    """
    key = key if key[:5] == 'sync_' else 'sync_' + key
    base_path = ['conversations']
    while True:
        try:
            return bot.config.get_by_path(base_path + [conv_id, key])
        except KeyError:
            pass
        if ':' not in conv_id:
            break
        conv_id = conv_id.rsplit(':', 1)[0]
    return bot.config[key]
