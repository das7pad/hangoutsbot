#TODO(das7pad) add documentation
import asyncio
import functools
import logging
import os
import ssl

from aiohttp import web

from hangupsbot.utils import class_from_name

from .base_bot_request_handler import AsyncRequestHandler

logger = logging.getLogger(__name__)

class ServerStorage(list):
    """storage for running aiohttp servers"""
    tracking = None

    def set_tracking(self, tracking):
        """store the plugin tracking

        Args:
            thracking (plugins.Tracker): the current instance
        """
        self.tracking = tracking

    async def clear(self):
        """remove all servers"""
        groups = [item[3] for item in self]
        await aiohttp_terminate(groups)

    def register_aiohttp_web(self, group):
        """add a single group to the plugin tracking

        Args:
            group (str): a new group
        """
        self.tracking.register_aiohttp_web(group)

aiohttp_servers = ServerStorage()


def start(bot):
    jsonrpc_sinks = bot.config.get_option('jsonrpc')
    if not isinstance(jsonrpc_sinks, list):
        return

    item_no = -1

    aiohttpcount = 0

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

            aiohttpcount = aiohttpcount + 1

        else:
            logger.critical(
                '%s is not an instance of `sinks.AsyncRequestHandler`, skipped',
                repr(handler_class))
            continue

    if aiohttpcount:
        logger.info("%s aiohttp web listener(s)", aiohttpcount)

def aiohttp_start(*, bot, name, port, certfile=None, requesthandlerclass, group,
                  callback=None):
    requesthandler = requesthandlerclass(bot)

    app = web.Application()
    requesthandler.addroutes(app.router)

    handler = app.make_handler()

    if certfile:
        sslcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        sslcontext.load_cert_chain(certfile)
    else:
        sslcontext = None

    loop = asyncio.get_event_loop()
    server = loop.create_server(handler, name, port, ssl=sslcontext)

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
