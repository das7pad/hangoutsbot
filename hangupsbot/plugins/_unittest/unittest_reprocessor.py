import asyncio

import plugins


def _initialise():
    plugins.register_admin_command(["testcoroutinecontext",
                                    "testnoncoroutinecontext"])


async def testcoroutinecontext(bot, event, *dummys):
    """test hidden context"""
    await bot.coro_send_message(
        event.conv_id,
        "This message has hidden context",
        context={
            "reprocessor": bot.call_shared("reprocessor.attach_reprocessor",
                                           coro_reprocess_the_event)})


async def testnoncoroutinecontext(bot, event, *dummys):
    """test hidden context"""
    await bot.coro_send_message(
        event.conv_id,
        "This message has hidden context",
        context={
            "reprocessor": bot.call_shared("reprocessor.attach_reprocessor",
                                           reprocess_the_event)})


async def coro_reprocess_the_event(bot, event, id_):
    await bot.coro_send_message(
        event.conv_id,
        """<em>coroutine responding to message with uuid: {}</em>\n"""
        """VISIBLE CONTENT WAS: {}""".format(id_, event.text))


def reprocess_the_event(bot, event, id_):
    asyncio.ensure_future(
        bot.coro_send_message(
            event.conv_id,
            """<em>non-coroutine responding to message with uuid: {}</em>\n"""
            """VISIBLE CONTENT WAS: {}""".format(id_, event.text)))
