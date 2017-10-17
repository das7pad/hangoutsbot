"""memory unit test
all these commands work on memory.json
* creating, updating, removing a string in memory["unittest"] (memory test)
* creating, updating, removing a string in memory["unittest"]["timestamp"] (submemory test)
* retrieving and setting taint status of memory
"""

import logging
import time

from hangupsbot import plugins


logger = logging.getLogger(__name__)


def _initialise():
    plugins.register_admin_command(["memorytaint", "memoryuntaint", "memorystatus",
                                    "memoryset", "memoryget", "memorypop", "memorysave", "memorydelete",
                                    "submemoryinit", "submemoryclear", "submemoryset", "submemoryget", "submemorypop", "submemorydelete"])


def memoryset(bot, *dummys):
    timestamp = time.time()
    bot.memory["unittest"] = str(timestamp)
    logger.info("memoryset: %s", timestamp)


def memoryget(bot, *dummys):
    logger.info("memoryget: %s", bot.memory["unittest"])


def memorypop(bot, *dummys):
    the_string = bot.memory.pop("unittest")
    logger.info("memorypop: %s", the_string)


def memorytaint(bot, *dummys):
    if bot.memory.changed:
        logger.info("memorytaint: memory already tainted")
    else:
        bot.memory.force_taint()
        logger.info("memorytaint: memory tainted")


def memoryuntaint(bot, *dummys):
    if bot.memory.changed:
        bot.memory.changed = False
        logger.info("memoryuntaint: memory de-tainted")
    else:
        logger.info("memoryuntaint: memory not tainted")


def memorystatus(bot, *dummys):
    if bot.memory.changed:
        logger.info("memorystatus: memory tainted")
    else:
        logger.info("memorystatus: memory not tainted")


def memorysave(bot, *dummys):
    bot.memory.save()


def submemoryinit(bot, *dummys):
    bot.memory["unittest-submemory"] = {}


def submemoryclear(bot, *dummys):
    bot.memory.pop("unittest-submemory")


def submemoryset(bot, *dummys):
    timestamp = time.time()
    bot.memory["unittest-submemory"]["timestamp"] = str(timestamp)
    logger.info("submemoryset: %s", timestamp)


def submemoryget(bot, *dummys):
    logger.info("submemoryget: %s", bot.memory["unittest-submemory"]["timestamp"])


def submemorypop(bot, *dummys):
    the_string = bot.memory["unittest-submemory"].pop("timestamp")
    logger.info("submemorypop: %s", the_string)


def memorydelete(bot, *dummys):
    the_string = bot.memory.pop_by_path(["unittest"])
    logger.info("memorydelete: %s", the_string)


def submemorydelete(bot, *dummys):
    the_string = bot.memory.pop_by_path(["unittest-submemory", "timestamp"])
    logger.info("submemorydelete: %s", the_string)
