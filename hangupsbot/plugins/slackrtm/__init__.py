"""Improved Slack sync plugin using the Slack RTM API and websockets.
(c) 2015 Patrick Cernko <errror@gmx.de>

async rewrite: das7pad@outlook.com

Create a new user and setup auth for each team you want to sync into hangouts.
Get an auth-token here: https://api.slack.com/custom-integrations/legacy-tokens

Your config.json should have a slackrtm section that looks something like this.
You only need one entry per Slack team.

    "slackrtm": [
        {
            "name": "CostomNameToFindTheSlackTeamViaHangoutsCommands",
            "domain": "my-team.slack.com",
            "key": "SLACK_TEAM1_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        },
        {
            "name": "OptionalSecondTeamWithItsCustomName",
            "domain": "my-second-team.slack.com",
            "key": "SLACK_TEAM2_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        }
    ]

  name : a custom slack team name
domain : the team domain at slack, important to track a domain-change performed
         while the bot is offline - otherwise we loose track of the memory entry
   key : slack bot api key for that team (xoxb-xxxxxxx...)
admins : user_ids from slack (to find them, you can use
                              https://api.slack.com/methods/users.list/test)

You can set up as many slack teams per bot as you like by extending the list.

Once the team(s) are configured, and the hangupsbot is restarted, invite the
newly created Slack user into any channel or group that you want to sync, and
then use the command from any slack channel:
    @hobot syncto <hangouts id>

Use "@hobot help" for more help on the Slack side.
"""

import logging

from hangupsbot import plugins

# reload the other modules
# pylint: disable=wrong-import-position,unused-import
for _path_ in ('exceptions', 'parsers', 'message', 'storage',
               'commands_hangouts', 'commands_slack', 'core'):
    plugins.load_module('plugins.slackrtm.' + _path_)

from .commands_hangouts import (
    HELP,
    slacks,
    slack_channels,
    slack_users,
    slack_listsyncs,
    slack_syncto,
    slack_disconnect,
)
from .core import SlackRTM
from .exceptions import SlackConfigError
from .storage import (
    SLACKRTMS,
    setup_storage,
)


logger = logging.getLogger(__name__)


def _initialise(bot):
    """migrate data, start SlackRTMs and register commands

    Args:
        bot (hangupsbot.HangupsBot): the running instance
    """
    setup_storage(bot)

    for sink_config in bot.get_config_option('slackrtm'):
        try:
            slackrtm = SlackRTM(sink_config)
        except SlackConfigError as err:
            logger.error(repr(err))
        else:
            SLACKRTMS.append(slackrtm)
            plugins.start_asyncio_task(slackrtm.start)
    logger.info('%d SlackRTM started', len(SLACKRTMS))

    plugins.register_admin_command([
        'slacks',
        'slack_channels',
        'slack_listsyncs',
        'slack_syncto',
        'slack_disconnect',
        'slack_users',
    ])
    plugins.register_help(HELP)
