"""
Improved Slack sync plugin using the Slack RTM API instead of webhooks.
(c) 2015 Patrick Cernko <errror@gmx.de>

async rewrite: das7pad@outlook.com

Create a new user and setup auth for each team you want to sync into hangouts.
Get an auth-token here: https://api.slack.com/custom-integrations/legacy-tokens

Your config.json should have a slackrtm section that looks something
like this.  You only need one entry per Slack team, not per channel,
unlike the legacy code.

    "slackrtm": [
        {
            "name": "SlackTeamNameForLoggingCommandsEtc",
            "domain": "my-team.slack.com",
            "key": "SLACK_TEAM1_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        },
        {
            "name": "OptionalSlackOtherTeamNameForLoggingCommandsEtc",
            "domain": "my-second-team.slack.com",
            "key": "SLACK_TEAM2_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        }
    ]

name = slack team name
domain = the team domain at slack, important to track a domain-change performed
         while the bot is offline - otherwise we loose track of the memory entry
key = slack bot api key for that team (xoxb-xxxxxxx...)
admins = user_id from slack (you can use https://api.slack.com/methods/auth.test/test to find it)

You can set up as many slack teams per bot as you like by extending the list.

Once the team(s) are configured, and the hangupsbot is restarted, invite
the newly created Slack bot into any channel or group that you want to sync,
and then use the command:
    @botname syncto <hangoutsid>

Use "@botname help" for more help on the Slack side and /bot help <command> on
the Hangouts side for more help.

"""

import logging

import plugins

# reload the other modules
# pylint: disable=wrong-import-position,unused-import
for _path_ in ('exceptions', 'parsers', 'message', 'utils', 'storage',
               'commands_hangouts', 'commands_slack', 'core'):
    plugins.load_module('plugins.slackrtm.' + _path_)

from .commands_hangouts import (
    slacks,
    slack_channels,
    slack_users,
    slack_listsyncs,
    slack_syncto,
    slack_disconnect,
)
from .core import SlackRTM
from .storage import (
    SLACKRTMS,
    setup_storage,
)


logger = logging.getLogger(__name__)


def _initialise(bot):
    setup_storage(bot)

    for sink_config in bot.get_config_option('slackrtm'):
        rtm = SlackRTM(bot, sink_config)
        plugins.start_asyncio_task(rtm.start())
        SLACKRTMS.append(rtm)
    logger.info("%d SlackRTM started", len(SLACKRTMS))

    plugins.register_admin_command([
        "slacks",
        "slack_channels",
        "slack_listsyncs",
        "slack_syncto",
        "slack_disconnect",
        "slack_users",
    ])
