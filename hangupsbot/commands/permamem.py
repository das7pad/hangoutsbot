import logging

from hangupsbot import plugins


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_admin_command([
        "dumpconv",
        "dumpunknownusers",
        "resetunknownusers",
        "refreshusermemory",
        "removeconvrecord",
        "makeallusersindefinite",
    ])


def dumpconv(bot, dummy, *args):
    """dump all conversations known to the bot"""
    text_search = " ".join(args)
    lines = []
    all_conversations = bot.conversations.get().items()
    for convid, convdata in all_conversations:
        if text_search.lower() not in convdata["title"].lower():
            continue

        lines.append(
            "`{}` <em>{}</em> {}\n... `{}` history: {} \n... <b>{}</b>".format(
                convid, convdata["source"], len(convdata["participants"]),
                convdata["type"], convdata["history"], convdata["title"]
            )
        )

    lines.append("<b><em>Totals: {}/{}</em></b>".format(len(lines),
                                                        len(all_conversations)))
    return "\n".join(lines)


def dumpunknownusers(bot, *dummys):
    """lists cached users records with full name, first name as unknown"""
    logger.info("dumpunknownusers started")

    if bot.memory.exists(["user_data"]):
        for chat_id in bot.memory["user_data"]:
            if "_hangups" not in bot.memory["user_data"][chat_id]:
                continue

            _hangups = bot.memory["user_data"][chat_id]["_hangups"]
            if not _hangups["is_definitive"]:
                continue

            if (_hangups["full_name"].upper() == "UNKNOWN"
                    and _hangups["full_name"] == _hangups["first_name"]):
                logger.info("dumpunknownusers %s", _hangups)

    logger.info("dumpunknownusers finished")

    return "<b>please see log/console</b>"


def resetunknownusers(bot, *dummys):
    """resets cached users records with full name, first name as unknown"""
    logger.info("resetunknownusers started")

    if bot.memory.exists(["user_data"]):
        for chat_id in bot.memory["user_data"]:
            if "_hangups" not in bot.memory["user_data"][chat_id]:
                continue

            _hangups = bot.memory["user_data"][chat_id]["_hangups"]
            if not _hangups["is_definitive"]:
                continue

            if (_hangups["full_name"].upper() == "UNKNOWN"
                    and _hangups["full_name"] == _hangups["first_name"]):
                logger.info("resetunknownusers %s", _hangups)
                bot.memory.set_by_path(
                    ["user_data", chat_id, "_hangups", "is_definitive"], False)

    bot.memory.save()

    logger.info("resetunknownusers finished")

    return "<b>please see log/console</b>"


async def refreshusermemory(bot, dummy, *args):
    """refresh specified user chat ids with contact/getentitybyid"""
    logger.info("refreshusermemory started")
    updated = await bot.conversations.get_users_from_query(args)
    logger.info("refreshusermemory %s updated", updated)
    logger.info("refreshusermemory ended")

    return "<b>please see log/console</b>"


def removeconvrecord(bot, dummy, *args):
    """removes conversation record from memory.json"""
    logger.info("resetunknownusers started")
    if args:
        for conv_id in args:
            bot.conversations.remove(conv_id)
    logger.info("resetunknownusers finished")

    return "<b>please see log/console</b>"


def makeallusersindefinite(bot, *dummys):
    """turn off the is_definite flag for all users"""
    logger.info("makeallusersindefinite started")

    if bot.memory.exists(["user_data"]):
        for chat_id in bot.memory["user_data"]:
            if "_hangups" not in bot.memory["user_data"][chat_id]:
                continue

            bot.memory.set_by_path(
                ["user_data", chat_id, "_hangups", "is_definitive"], False)

    bot.memory.save()

    logger.info("makeallusersindefinite finished")

    return "<b>please see log/console</b>"
