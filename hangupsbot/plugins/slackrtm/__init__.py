"""
Improved Slack sync plugin using the Slack RTM API instead of webhooks.
(c) 2015 Patrick Cernko <errror@gmx.de>

async rewrite: das7pad@outlook.com

Create a Slack bot integration (not webhooks!) for each team you want
to sync into hangouts.

Your config.json should have a slackrtm section that looks something
like this.  You only need one entry per Slack team, not per channel,
unlike the legacy code.

    "slackrtm": [
        {
            "name": "SlackTeamNameForLoggingCommandsEtc",
            "key": "SLACK_TEAM1_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        },
        {
            "name": "OptionalSlackOtherTeamNameForLoggingCommandsEtc",
            "key": "SLACK_TEAM2_BOT_API_KEY",
            "admins": [ "U01", "U02" ]
        }
    ]

name = slack team name
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
               'commands_hangouts', 'commands_slack', 'bridgeinstance', 'core'):
    plugins.load_module('plugins.slackrtm.' + _path_)

from .commands_hangouts import (
    slacks,
    slack_channels,
    slack_users,
    slack_listsyncs,
    slack_syncto,
    slack_disconnect,
    slack_setsyncjoinmsgs,
    slack_sethotag,
    slack_setslacktag,
    slack_showslackrealnames,
    slack_showhorealnames,
    slack_identify,
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
        "slack_setsyncjoinmsgs",
        "slack_setimageupload",
        "slack_sethotag",
        "slack_users",
        "slack_setslacktag",
        "slack_showslackrealnames",
        "slack_showhorealnames",
    ])

    plugins.register_user_command(["slack_identify"])
