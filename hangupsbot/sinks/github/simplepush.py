import json
import logging

from sinks.base_bot_request_handler import AsyncRequestHandler


logger = logging.getLogger(__name__)


class webhookReceiver(AsyncRequestHandler):
    _bot = None

    async def process_request(self, path, query_string, content):
        path = path.split("/")
        conv_or_user_id = path[1]
        if conv_or_user_id is None:
            logger.error("conv id or user id must be provided as part of path")
            return

        try:
            payload = json.loads(content)
        except ValueError:
            logger.exception("invalid payload")

        if all(key in payload for key in ('repository', 'commits', 'pusher')):
            html = '<b>{}</b> has <a href="{}">pushed</a> {} commit{}\n'.format(
                payload["pusher"]["name"], payload["repository"]["url"],
                len(payload["commits"]),
                's' if len(payload["commits"]) == 1 else '')

            for commit in payload["commits"]:
                html += '* <i>{}</i> <a href="{}">link</a>\n'.format(
                    commit["message"], commit["url"])

            await self.send_data(conv_or_user_id, html)

        elif "zen" in payload:
            logger.info("github zen received: {}".format(payload["zen"]))

        else:
            logger.error("unrecognised payload: {}".format(payload))
