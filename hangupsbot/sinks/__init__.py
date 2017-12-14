#TODO(das7pad) add documentation
import asyncio
import functools
import logging
import os
import ssl

from aiohttp import web

from hangupsbot.base_models import TrackingMixin
from hangupsbot.utils import class_from_name

from .base_bot_request_handler import AsyncRequestHandler

logger = logging.getLogger(__name__)

class ServerStorage(list, TrackingMixin):
    """storage for running aiohttp servers"""

    def register_aiohttp_web(self, group):
        """add a single group to the plugin tracking

        Args:
            group (str): a new group
        """
        self.tracking.register_aiohttp_web(group)

aiohttp_servers = ServerStorage()                  # pylint:disable=invalid-name


def start(bot):
    jsonrpc_sinks = bot.config.get_option('jsonrpc')
    if not isinstance(jsonrpc_sinks, list):
        return

    item_no = -1

    aiohttp_count = 0

    for sink_config in jsonrpc_sinks:
        item_no += 1

        try:
            module = sink_config["module"].split(".")
            if len(module) < 3:
                logger.error("config.jsonrpc[%s].module should have at least 3"
                             " packages %s", item_no, module)
                continue

            module_name = ".".join(module[0:-1])
            class_name = ".".join(module[-1:])
            if not module_name or not class_name:
                logger.error("config.jsonrpc[%s].module must be a valid package"
                             " name", item_no)
                continue

            certfile = sink_config.get("certfile")
            if certfile and not os.path.isfile(certfile):
                logger.error("config.jsonrpc[%s].certfile not available at %s",
                             item_no, certfile)
                continue

            name = sink_config["name"]
            port = sink_config["port"]
        except KeyError as err:
            logger.error("config.jsonrpc[%s] missing keyword %s", item_no, err)
            continue

        try:
            handler_class = class_from_name(module_name, class_name)

        except (AttributeError, ImportError):
            logger.error("not found: %s %s", module_name, class_name)
            continue

        # start up rpc listener in a separate thread

        logger.debug("starting sink: %s", module)

        if issubclass(handler_class, AsyncRequestHandler):
            aiohttp_start(
                bot=bot,
                name=name,
                port=port,
                certfile=certfile,
                requesthandlerclass=handler_class,
                group="json-rpc")

            aiohttp_count = aiohttp_count + 1

        else:
            logger.critical(
                '%s is not an instance of `sinks.AsyncRequestHandler`, skipped',
                repr(handler_class))
            continue

    if aiohttp_count:
        logger.info("%s aiohttp web listener(s)", aiohttp_count)

def aiohttp_start(*, bot, name, port, certfile=None, requesthandlerclass, group,
                  callback=None):
    request_handler = requesthandlerclass(bot)

    app = web.Application()
    request_handler.addroutes(app.router)

    handler = app.make_handler()

    if certfile:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_context.load_cert_chain(certfile)
    else:
        ssl_context = None

    loop = asyncio.get_event_loop()
    server = loop.create_server(handler, name, port, ssl=ssl_context)

    asyncio.ensure_future(server).add_done_callback(
        functools.partial(aiohttp_started, handler=handler, app=app,
                          group=group, callback=callback))

    aiohttp_servers.register_aiohttp_web(group)

def aiohttp_started(future, handler, app, group, callback=None):
    server = future.result()
    constructors = (server, handler, app, group)

    aiohttp_servers.append(constructors)

    logger.info("aiohttp: %s on %s", group, server.sockets[0].getsockname())

    if callback:
        callback(constructors)

def aiohttp_list(groups):
    if isinstance(groups, str):
        groups = [groups]

    filtered = []
    for constructors in aiohttp_servers:
        if constructors[3] in groups:
            filtered.append(constructors)

    return filtered

async def aiohttp_terminate(groups):
    removed = []
    for constructors in aiohttp_list(groups):
        [server, handler, app, dummy] = constructors

        await handler.finish_connections(1.0)
        server.close()
        await server.wait_closed()
        await app.finish()

        logger.info("aiohttp: terminating %s %s", constructors[3], constructors)
        removed.append(constructors)

    for constructors in removed:
        aiohttp_servers.remove(constructors)
