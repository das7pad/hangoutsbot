import logging
import pprint

from hangupsbot import plugins


logger = logging.getLogger(__name__)

_PP = pprint.PrettyPrinter(indent=2)


def _initialise():
    plugins.register_admin_command([
        "testcontext",
    ])
    plugins.register_handler(_handle_incoming_message, "allmessages")


def testcontext(dummy, event, *dummys):
    """test annotation with some tags"""
    tags = ['text', 'longer-text', 'text with symbols:!@#$%^&*(){}']
    return (
        event.conv_id,
        "this message has context - please see your console/log",
        {
            "tags": tags,
            "passthru": {
                "random_variable": "hello world!",
                "some_dictionary": {"var1": "a", "var2": "b"},
            }
        })


async def _handle_incoming_message(dummy, event):
    """BEWARE OF INFINITE MESSAGING LOOPS!

    all bot messages have context, and if you send a message here
    it will also have context, triggering this handler again"""

    # output to log
    if event.passthru:
        logger.info("passthru received: %s", event.passthru)
    if event.context:
        logger.info("context received: %s", event.context)

    # output to stdout
    if event.passthru:
        print("--- event.passthru")
        _PP.pprint(event.passthru)
    if event.context:
        print("--- event.context")
        _PP.pprint(event.context)
