"""API plugin for listening for server commands and treating them as ConversationEvents
config.json will have to be configured as follows:

"api_key": "API_KEY",
"api": [{
  "certfile": null,
  "name": "SERVER_NAME",
  "port": LISTENING_PORT
}]

Also you will need to append the bot's own user_id to the admin list if you want
to be able to run admin commands externally

More info: https://github.com/hangoutsbot/hangoutsbot/wiki/API-Plugin
"""
import asyncio
import functools
import json
import logging
import time

from urllib.parse import unquote

from aiohttp import web

from sinks import aiohttp_start
from sinks.base_bot_request_handler import AsyncRequestHandler


logger = logging.getLogger(__name__)


def _initialise(bot):
    _start_api(bot)

reprocessor_queue = {}


def response_received(dummy0, dummy1, dummy2, results, original_id):
    if results:
        if isinstance(results, dict) and "api.response" in results:
            output = results["api.response"]
        else:
            output = results
        reprocessor_queue[original_id] = output


def handle_as_command(bot, event, original_id):
    event.from_bot = False
    event.syncroom_no_repeat = True

    if "acknowledge" not in dir(event):
        event.acknowledge = []

    handle_response = functools.partial(response_received,
                                        original_id=original_id)
    event.acknowledge.append(bot._handlers.register_reprocessor(handle_response))


def _start_api(bot):
    api = bot.config.get_option('api')
    itemNo = -1

    if isinstance(api, list):
        for sinkConfig in api:
            itemNo += 1

            try:
                certfile = sinkConfig["certfile"]
                if not certfile:
                    logger.error("config.api[%s].certfile must be configured",
                                 itemNo)
                    continue
                name = sinkConfig["name"]
                port = sinkConfig["port"]
            except KeyError as err:
                logger.error("config.api[%s] missing keyword: %s",
                             itemNo, repr(err))
                continue

            aiohttp_start(
                bot=bot,
                name=name,
                port=port,
                certfile=certfile,
                requesthandlerclass=APIRequestHandler,
                group=__name__)


class APIRequestHandler(AsyncRequestHandler):
    def addroutes(self, router):
        router.add_route("OPTIONS", "/", self.adapter_do_OPTIONS)
        router.add_route("POST", "/", self.adapter_do_POST)
        router.add_route('GET', '/{api_key}/{id}/{message:.*?}', self.adapter_do_GET)


    async def adapter_do_OPTIONS(self, request):
        origin = request.headers["Origin"]

        allowed_origins = self._bot.config.get_option("api_origins")
        if allowed_origins is None:
            raise web.HTTPForbidden()

        if allowed_origins == "*" or "*" in allowed_origins:
            return web.Response(headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "content-type",
            })

        if not origin in allowed_origins:
            raise web.HTTPForbidden()

        return web.Response(headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "content-type",
            "Vary": "Origin",
        })

    async def adapter_do_GET(self, request):
        payload = {"sendto": request.match_info["id"],
                   "key": request.match_info["api_key"],
                   "content": unquote(request.match_info["message"])}

        results = await self.process_request('', # IGNORED
                                             '', # IGNORED
                                             payload)
        if results:
            content_type = "text/html"
            results = results.encode("ascii", "xmlcharrefreplace")
        else:
            content_type = "text/plain"
            results = "OK".encode('utf-8')

        return web.Response(body=results, content_type=content_type)

    async def process_request(self, path, query_string, content):
        # XXX: bit hacky due to different routes...
        payload = content
        if isinstance(payload, str):
            # XXX: POST - payload in incoming request BODY (and not yet parsed, do it here)
            payload = json.loads(payload)
        # XXX: else GET - everything in query string (already parsed before it got here)

        api_key = self._bot.config.get_option("api_key")

        if payload["key"] != api_key:
            raise ValueError("API key does not match")

        results = await self.send_actionable_message(payload["sendto"],
                                                     payload["content"])

        return results

    async def send_actionable_message(self, target, content):
        """reprocessor: allow message to be intepreted as a command"""
        reprocessor_context = self._bot.call_shared(
            "reprocessor.attach_reprocessor", handle_as_command)
        reprocessor_id = reprocessor_context["id"]

        if target in self._bot.conversations:
            results = await self._bot.coro_send_message(
                target,
                content,
                context={"reprocessor": reprocessor_context})

        else:
            # attempt to send to a user id
            results = await self._bot.coro_send_to_user(
                target,
                content,
                context={"reprocessor": reprocessor_context})

        start_time = time.time()
        while time.time() - start_time < 3:
            if reprocessor_id in reprocessor_queue:
                response = reprocessor_queue[reprocessor_id]
                del reprocessor_queue[reprocessor_id]
                return "[" + str(time.time() - start_time) + "] " + response
            await asyncio.sleep(0.1)

        return results
