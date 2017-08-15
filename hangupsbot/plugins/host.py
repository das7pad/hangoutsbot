"""host utils"""
__author__ = 'das7pad@outlook.com'

from datetime import timedelta, datetime
import os

import psutil

import plugins

HELP = {
    'uptime': _('post the current sytem uptime in our private chat'),
}

def _initialise():
    """register the admin command"""
    plugins.register_admin_command([
        'uptime',
    ])

    plugins.register_help(HELP)

def _seconds_to_str(seconds):
    """get a printable representation of a timespawn

    Args:
        seconds: int, number of seconds in the timespawn

    Returns:
        string, pretty output
    """
    return str(timedelta(seconds=seconds)).split('.')[0]

def _uptime_in_seconds(now):
    """get the system uptime in seconds

    Args:
        now: datetime.datetime instance

    Returns:
        float, time in seconds since the last boot
    """
    return now.timestamp() - psutil.boot_time()

async def uptime(bot, event, *dummys):
    """display the current system uptime

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        dummys: unused
    """
    now = datetime.today()
    today = now.strftime('%Y-%m-%d %H:%M:%S')
    loadavg = os.getloadavg()
    onlinetime = _seconds_to_str(_uptime_in_seconds(now))
    process = psutil.Process()
    bot_uptime = _seconds_to_str(now.timestamp() - process.create_time())
    lines = [today,
             'server uptime:  ' + onlinetime,
             'server load:       {}  {}  {}'.format(
                 loadavg[0], loadavg[1], loadavg[2]),
             'bot uptime:        ' + bot_uptime]
    await bot.coro_send_to_user(event.user_id.chat_id, '\n'.join(lines))
