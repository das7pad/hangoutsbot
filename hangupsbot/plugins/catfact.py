import logging
import plugins
import requests

logger = logging.getLogger(__name__)

HELP = {
    'catfact': _('get catfacts'),
}

def _initialise():
    plugins.register_user_command(["catfact"])
    plugins.register_help(HELP)

def catfact(dummy0, dummy1, number=1):
    try:
        r = requests.get("https://catfact.ninja/facts?limit={}".format(number))
        facts = [fact['fact'] for fact in r.json()['data']]
        html_text = '<br>'.join(facts)
    except (requests.RequestException, ValueError, KeyError):
        html_text = "Unable to get catfacts right now"
        logger.exception(html_text)

    return html_text
