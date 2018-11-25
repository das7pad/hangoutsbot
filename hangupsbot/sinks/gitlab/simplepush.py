"""
GitLab webhook receiver - see http://doc.gitlab.com/ee/web_hooks/web_hooks.html
"""

import json
import logging

import dateutil.parser

from hangupsbot.sinks.base_bot_request_handler import SimpleAsyncRequestHandler


logger = logging.getLogger(__name__)


class GitlabWebHookReceiver(SimpleAsyncRequestHandler):
    """Receive REST API posts from GitLab"""
    logger = logger

    async def process_payload(self, conv_or_user_id, payload):
        """Process a received POST to a given conversation"""
        logger.info("GitLab message: %s", json.dumps(payload))

        refs = payload.get("ref", '').split("/")

        user = payload.get("user_name")
        if not user:
            user = payload["user"]["name"]

        message = ["GitLab update for [{}]({}) by __{}__".format(
            payload["project"]["name"], payload["project"]["web_url"], user)]

        if payload["object_kind"] == "push":
            message.append("Pushed {} commit(s) on {} branch:".format(
                payload["total_commits_count"], "/".join(refs[2:])))

            for commit in payload["commits"]:
                message.append("{} -- {} at [{:%c}]({})".format(
                    commit["message"], commit["author"]["name"],
                    dateutil.parser.parse(commit["timestamp"]), commit["url"]))

        elif payload["object_kind"] == "tag_push":
            message.append("Pushed tag {}]".format("/".join(refs[2:])))

        elif payload["object_kind"] == "issue":
            issue = payload["object_attributes"]
            message.append("Update {} issue {} at {:%c}\n[{}]({})".format(
                issue["state"], issue["id"],
                dateutil.parser.parse(issue["updated_at"]),
                issue["title"], issue["url"]))

        elif payload["object_kind"] == "note":
            note = payload["object_attributes"]
            message.append("{} note on {}: [{}]({})".format(
                note["notable_type"], note["id"], note["note"], note["url"]))

        elif payload["object_kind"] == "merge_request":
            request = payload["object_attributes"]
            message.append(
                "Merge request {}: from [{}:{}]({}) to [{}:{}]({})".format(
                    request["id"],
                    request["source"]["name"], request["source_branch"],
                    request["source"]["web_url"],
                    request["target"]["name"], request["target_branch"],
                    request["target"]["web_url"]))

        else:
            message.append("{}: unknown gitlab webhook object kind".format(
                payload["object_kind"]))
            logger.error(
                "unknown gitlab webhook object kind: %r",
                payload["object_kind"]
            )

        if message:
            await self.send_data(conv_or_user_id, "\n".join(message))
