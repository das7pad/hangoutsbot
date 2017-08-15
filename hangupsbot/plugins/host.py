"""host utils

requirements for advanced report_online functionality:
    a running datadog service on your host and the datadog module:
        $ /path/to/venv/pip3 install datadog

    The command "report_online" can start periodic incrementation of the metric
    "hangupsbot.online.<botname>", the intervall is set to 30 seconds
    In addition datadog events are fired on bot start and on bot shutdown.


Additional config entrys that can be set manually:
    - "load_threshold": <int>
      threshold for the 5min load value of the system to trigger a notification,
      defaults to the cpu count

    - "datadog_notify_in_events": <string>
      add a custom text to each event, e.g. "@slack" to get the message into a
      connected slack, use \n to add a linebreak
"""
__author__ = 'das7pad@outlook.com'

import asyncio
from datetime import timedelta, datetime
import os
import time

try:
    from datadog import statsd
except ImportError:
    statsd = None
import psutil

import plugins

HELP = {
    'check_load': _('enable/disable system load reporting above an average 1 '
                    'load per core into the current conv\n\n'
                    '<i>The threshold can be set manually to a different value:'
                    '\n  set "load_threshold" in your config to a custom value'
                    '</i>'),
    'report_online': _('enable/disable sending of a message into the current '
                       'conv on bot reboot\n<i>datadog: toggles the periodic '
                       'reporting of an online state of the bot to '
                       'datadog - this requires an active datadog service</i>'),
    'uptime': _('post the current sytem uptime in our private chat'),
    'who': _('list current ssh-session on the host in our private chat')
}

def _initialise(bot):
    """register the admin commands and start the coros

    Args:
        bot: HangupsBot instance
    """
    plugins.register_admin_command([
        'check_load',
        'report_online',
        'uptime',
        'who',
    ])

    plugins.register_help(HELP)
    plugins.start_asyncio_task(_check_load)
    plugins.start_asyncio_task(_report_online)

    bot.config.set_defaults({
        'check_load': [],
        'datadog_notify_in_events': '',
        'load_threshold': (os.cpu_count() or 1),
        'report_online': [],
    })

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

async def _update(bot, event, feature):
    """flip the state of a given feature and reload the plugin

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        feature: string, plugin feature to update targets for
    """
    targets = bot.config.get_option(feature) or []   # do not overwrite defaults
    target = event.conv_id
    output = _('Notifications ')

    if target in targets:
        targets.remove(target)
        output += _('disabled')
    else:
        targets.append(target)
        output += _('enabled')

    bot.config.set_by_path([feature], targets)
    bot.config.save()

    await bot.coro_send_message(event.conv_id, output)

    asyncio.ensure_future(plugins.reload_plugin(bot, 'plugins.host'))

async def check_load(bot, event, *dummys):
    """add/remove the current conv_id from 'check_load' in config

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        dummys: unused
    """
    await _update(bot, event, 'check_load')

async def report_online(bot, event, *dummys):
    """add/remove the current conv_id from 'report_online' in config

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        dummys: unused
    """
    await _update(bot, event, 'report_online')

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

async def _report_online(bot):
    """report the startup and send periodically an online state to datadog

    Args:
        bot: HangupsBot instance
    """
    if not bot.config.get_option('report_online'):
        return

    bot_user = bot.user_self()  # dict with user info
    bot_name = bot_user['full_name'].split()[0]

    title_template = _('{name} is back up')

    process = psutil.Process()
    startup = datetime.strftime(datetime.fromtimestamp(process.create_time()),
                                '%Y-%m-%d %H:%M:%S')

    title = title_template.format(name='<b>%s</b>' % bot_name)

    message = title + '\nstarted on %s' % startup
    for conv_id in bot.config['report_online'].copy():
        await bot.coro_send_message(conv_id, message)

    if statsd is None:
        # datadog module is not available
        return

    body = _('HangupsBot using user https://plus.google.com/{chat_id}\n'
             'started on {startup}').format(chat_id=bot_user['chat_id'],
                                            startup=startup)

    bot_name = (''.join(char for char in bot_name if char.isalnum())
                or _('bot_name'))
    additional_mentions = bot.config['datadog_notify_in_events']
    if additional_mentions:
        body += '\nNotify: %s' % additional_mentions
    statsd.event(title_template.format(name=bot_name), body,
                 alert_type='success')

    try:
        while bot.config.get_option('report_online'):
            statsd.set('hangupsbot.online.{}'.format(bot_name), 1)
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        statsd.event(_('{name} is going down').format(name=bot_name), body,
                     alert_type='warning')

async def _check_load(bot):
    """check periodically the system load and notify above the threshold

    Args:
        bot: HangupsBot instance
    """
    if not bot.config.get_option('check_load'):
        return

    try:
        while bot.config.get_option('check_load'):
            loadavg = os.getloadavg()
            load_threshold = bot.config['load_threshold']

            if loadavg[2] > load_threshold:
                now = datetime.today()
                today = datetime.strftime(now, '%Y-%m-%d %H:%M:%S')

                onlinetime = _seconds_to_str(_uptime_in_seconds(now))
                output = ('<b>LOAD-WARNING</b>\n{}\n'
                          'server uptime:  {}\nserver load:       {}  {}  {}'
                         ).format(today, onlinetime,
                                  loadavg[0], loadavg[1], loadavg[2])

                for conv_id in bot.config['check_load'].copy():
                    await bot.coro_send_message(conv_id, output)

                await asyncio.sleep(600)        # do not spam with load warnings
            elif loadavg[1] > load_threshold:
                # we might hit the treshold soon
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(300)
    except asyncio.CancelledError:
        return
