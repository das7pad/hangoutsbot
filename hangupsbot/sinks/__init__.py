#TODO(das7pad) refactor of aiohttp_start needed, it uses asyncio.async
#TODO(das7pad) add documentation
import asyncio
import functools
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import os
import ssl
import threadmanager

from aiohttp import web

import plugins
from utils import class_from_name

# pylint: disable=unused-import
from .base_bot_request_handler import AsyncRequestHandler, BaseBotRequestHandler

logger = logging.getLogger(__name__)

aiohttp_servers = []


def start(bot):
    shared_loop = asyncio.get_event_loop()

    jsonrpc_sinks = bot.config.get_option('jsonrpc')
    if not isinstance(jsonrpc_sinks, list):
        return

    item_no = -1

    threadcount = 0
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
                bot,
                name,
                port,
                certfile,
                handler_class,
                "json-rpc")

            aiohttpcount = aiohttpcount + 1

        else:
            threadmanager.start_thread(start_listening, args=(
                bot,
                shared_loop,
                name,
                port,
                certfile,
                handler_class,
                module_name))

            threadcount = threadcount + 1

    if threadcount:
        logger.info("%s threaded listener(s)", threadcount)

    if aiohttpcount:
        logger.info("%s aiohttp web listener(s)", aiohttpcount)


def start_listening(bot=None, loop=None, name="", port=8000, certfile=None,
                    webhook_receiver=BaseHTTPRequestHandler,
                    friendly_name="UNKNOWN"):
    if loop:
        asyncio.set_event_loop(loop)

    if bot:
        webhook_receiver._bot = bot

    try:
        httpd = HTTPServer((name, port), webhook_receiver)

        if certfile:
            httpd.socket = ssl.wrap_socket(
                httpd.socket,
                certfile=certfile,
                server_side=True)

        socket = httpd.socket.getsockname()

        logger.info("%s : %s:%s...", friendly_name, socket[0], socket[1])

        httpd.serve_forever()

    except ssl.SSLError:
        logger.exception("%s : %s:%s, pem file is invalid/corrupt",
                         friendly_name, name, port)

    except OSError as err:
        if err.errno == 2:
            message = ".pem file is missing/unavailable"
        elif err.errno == 98:
            message = "address/port in use"
        else:
            message = str(err.strerror)

        logger.exception("%s : %s:%s, %s", friendly_name, name, port, message)

        try:
            httpd.socket.close()
        except:
            pass

    except KeyboardInterrupt:
        httpd.socket.close()



def aiohttp_start(bot, name, port, certfile, requesthandlerclass, group,
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

    asyncio.async(server).add_done_callback(
        functools.partial(aiohttp_started, handler=handler, app=app,
                          group=group, callback=callback))

    plugins.tracking.register_aiohttp_web(group)

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
