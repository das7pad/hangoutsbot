"""
simple "ask" function for wolfram alpha data
credit goes to @billius for the original plugin

instructions:
* pip3 install wolframalpha
* get API KEY from http://products.wolframalpha.com/developers/
* put API KEY in config.json:wolframalpha-apikey
"""

import wolframalpha
import plugins
import logging

logger = logging.getLogger(__name__)

_internal = {}


def _initialise(bot):
    apikey = bot.config.get_option("wolframalpha-apikey")
    if apikey:
        _internal["client"] = wolframalpha.Client(apikey)
        plugins.register_user_command(["ask"])
    else:
        logger.info('WOLFRAMALPHA: config["wolframalpha-apikey"] required')


def ask(bot, event, *args):
    """request data from wolfram alpha"""

    if not args:
        return _("You need to ask WolframAlpha a question")

    keyword = ' '.join(args)
    res = _internal["client"].query(keyword)

    html = '<b>"{}"</b>\n\n'.format(keyword)

    has_content = False
    for pod in res.pods:
        if pod.title:
            html += "<b>{}:</b> ".format(pod.title)

        if pod.text and pod.text.strip():
            html += pod.text.strip() + "\n"
            has_content = True
        else:
            for node in pod.node.iter():
                if node.tag == "img":
                    html += '<a href="' + node.attrib["src"] + '">' + node.attrib["src"] + "</a>\n"
                    has_content = True

    if not has_content:
        html = _("<i>Wolfram Alpha did not return any useful data</i>")

    return html
