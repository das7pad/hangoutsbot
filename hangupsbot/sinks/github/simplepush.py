import logging

from hangupsbot.sinks.base_bot_request_handler import SimpleAsyncRequestHandler


logger = logging.getLogger(__name__)


class GitlabWebHookReceiver(SimpleAsyncRequestHandler):
    logger = logger

    async def process_payload(self, conv_or_user_id, payload):
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
            logger.info("github zen received: %s", payload["zen"])

        else:
            logger.error("unrecognised payload: %s", payload)
