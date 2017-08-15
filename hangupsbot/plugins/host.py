"""host utils"""
__author__ = 'das7pad@outlook.com'

from datetime import timedelta, datetime
import os
import time

import psutil

import plugins

HELP = {
    'uptime': _('post the current sytem uptime in our private chat'),
    'who': _('list current ssh-session on the host in our private chat')
}

def _initialise():
    """register the admin commands"""
    plugins.register_admin_command([
        'uptime',
        'who',
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

async def who(bot, event, *dummys):
    """display ssh-sessions

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        dummys: unused
    """
    today = datetime.today().strftime('%Y-%m-%d %H:%M:%S')
    lines = [today]
    sessions = psutil.users()
    if sessions:
        header = (_('user'), _('terminal'), _('host'), _('session-time'))
        space = header_space = [len(item) for item in header]
        raw_output = []
        now = time.time()
        for session in sessions:
            row = *session[:-1], _seconds_to_str(now - session.started)

            # update the spaces for lines
            space = [space[pos] if space[pos] > len(row[pos])
                     else len(row[pos])
                     for pos in range(4)]

            raw_output.append(row)

        for row in raw_output:
            # align the output
            # Hangouts blanks are about two 'normal' ones
            row = ['{value:<{wid}}'.format(value=row[pos], wid=space[pos])
                   .replace(' ', '  ').replace(' '*7, ' '*8)
                   for pos in range(4)]

            lines.append('  '.join(row))

            # update the spaces for the header
            header_space = [header_space[pos]
                            if header_space[pos] > len(row[pos])
                            else len(row[pos])
                            for pos in range(4)]

        lines.insert(1, ' '.join('{value:^{wid}}'.format(value=header[pos],
                                                         wid=header_space[pos])
                                 for pos in range(4)))
    else:
        lines.append('no active ssh-sessions')

    output = '\n'.join(lines)
    await bot.coro_send_to_user(event.user_id.chat_id, output)
