import logging

import aiohttp

from hangupsbot import plugins
from hangupsbot.utils import unicode_to_ascii

logger = logging.getLogger(__name__)

HELP = {
    'lookup': _('find keywords in a specified spreadsheet'),
}

def _initialise():
    plugins.register_user_command(["lookup"])
    plugins.register_help(HELP)


async def lookup(bot, event, *args):
    """find keywords in a specified spreadsheet"""

    if not bot.get_config_suboption(event.conv_id, 'spreadsheet_enabled'):
        return _("Spreadsheet function disabled")

    if not bot.get_config_suboption(event.conv_id, 'spreadsheet_url'):
        return _("Spreadsheet URL not set")

    spreadsheet_url = bot.get_config_suboption(event.conv_id, 'spreadsheet_url')
    table_class = "waffle" # Name of table class to search. Note that 'waffle' seems to be the default for all spreadsheets

    if args[0].startswith('<'):
        counter_max = int(args[0][1:]) # Maximum rows displayed per query
        keyword = ' '.join(args[1:])
    else:
        counter_max = 5
        keyword = ' '.join(args)

    message = _('Results for keyword <b>{}</b>:\n').format(keyword)

    logger.debug("%s (%s) has requested to lookup '%s'",
                 event.user.full_name, event.user_id.chat_id, keyword)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(spreadsheet_url) as response:
                response.raise_for_status()
                html = await response.text()
    except aiohttp.ClientError as err:
        logger.info('request %s: %r', id(args), spreadsheet_url)
        logger.error('request %s: failed: %r', id(args), err)
        return _('lookup: request failed :(')

    keyword_raw = keyword.strip().lower()
    keyword_ascii = unicode_to_ascii(keyword_raw)

    data = []

    counter = 0

    # Adapted from http://stackoverflow.com/questions/23377533/python-beautifulsoup-parsing-table
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', attrs={'class':table_class})
    table_body = table.find('tbody')

    rows = table_body.find_all('tr')

    for row in rows:
        col = row.find_all('td')
        cols = [ele.text.strip() for ele in col]
        data.append([ele for ele in cols if ele]) # Get rid of empty values

    for row in data:
        for cell in row:
            cell_content_raw = str(cell).lower().strip()
            cell_content_ascii = unicode_to_ascii(cell_content_raw)

            if keyword_raw in cell_content_raw or keyword_ascii in cell_content_ascii:
                if counter < counter_max:
                    message += _('\nRow {}: ').format(counter+1)
                    for data_point in row:
                        message += '{} | '.format(data_point)
                    message += '\n'
                    counter += 1
                    break # prevent multiple subsequent cell matches appending identical rows
                else:
                    # count row matches only beyond the limit, to avoid over-long message
                    counter += 1

    if counter > counter_max:
        message += _('\n{0} rows found. Only returning first {1}.').format(counter, counter_max)
        if counter_max == 5:
            message += _('\nHint: Use <b>/bot lookup <{0} {1}</b> to view {0} rows').format(counter_max*2, keyword)

    if counter == 0:
        message += _('No match found')

    return message
