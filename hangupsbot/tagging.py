import logging
import re

from hangupsbot.base_models import BotMixin
from hangupsbot.commands import command


logger = logging.getLogger(__name__)


class Tags(BotMixin):
    regex_allowed = r"a-z0-9._\-"  # +command.deny_prefix

    wildcard = {
        "conversation": "*",
        "user": "*",
        "group": "GROUP",
        "one2one": "ONE_TO_ONE",
    }

    indices = {}

    def __init__(self):
        self.refresh_indices()

    def _load_from_memory(self, key, tag_type):
        if self.bot.memory.exists([key]):
            for id_, data in self.bot.memory[key].items():
                if "tags" in data:
                    for tag in data["tags"]:
                        self.add_to_index(tag_type, tag, id_)

    def refresh_indices(self):
        self.indices = {
            "user-tags": {},
            "tag-users": {},
            "conv-tags": {},
            "tag-convs": {},
        }

        self._load_from_memory("user_data", "user")
        self._load_from_memory("conv_data", "conv")

        # XXX: custom iteration to retrieve per-conversation-user-overrides
        if self.bot.memory.exists(["conv_data"]):
            for conv_id in self.bot.memory["conv_data"]:
                path = ["conv_data", conv_id, "tags-users"]
                if not self.bot.memory.exists(path):
                    continue

                for chat_id, tags in self.bot.memory.get_by_path(path).items():
                    for tag in tags:
                        self.add_to_index("user", tag, conv_id + "|" + chat_id)

        logger.info("refreshed")

    def add_to_index(self, tag_type, tag, id_):
        tag_to_object = "tag-{}s".format(tag_type)
        object_to_tag = "{}-tags".format(tag_type)

        if tag not in self.indices[tag_to_object]:
            self.indices[tag_to_object][tag] = []
        if id_ not in self.indices[tag_to_object][tag]:
            self.indices[tag_to_object][tag].append(id_)

        if id_ not in self.indices[object_to_tag]:
            self.indices[object_to_tag][id_] = []
        if tag not in self.indices[object_to_tag][id_]:
            self.indices[object_to_tag][id_].append(tag)

    def remove_from_index(self, tag_type, tag, id_):
        tag_to_object = "tag-{}s".format(tag_type)
        object_to_tag = "{}-tags".format(tag_type)

        if tag in self.indices[tag_to_object]:
            if id_ in self.indices[tag_to_object][tag]:
                self.indices[tag_to_object][tag].remove(id_)
                if not self.indices[tag_to_object][tag]:
                    # remove key entirely it its empty
                    del self.indices[tag_to_object][tag]

        if id_ in self.indices[object_to_tag]:
            if tag in self.indices[object_to_tag][id_]:
                self.indices[object_to_tag][id_].remove(tag)
                if not self.indices[object_to_tag][id_]:
                    # remove key entirely it its empty
                    del self.indices[object_to_tag][id_]

    def update(self, tag_type, id_, action, tag):
        updated = False
        tags = None

        if tag_type == "conv":
            index_type = "conv"

            if (id_ not in self.bot.conversations and
                    id_ not in (self.wildcard["group"],
                                self.wildcard["one2one"],
                                self.wildcard["conversation"])):
                raise ValueError("conversation {} does not exist".format(id_))

            tags = self.bot.conversation_memory_get(id_, "tags")

        elif tag_type == "user":
            index_type = "user"

            if (not self.bot.memory.exists(["user_data", id_]) and
                    id_ != self.wildcard["user"]):
                raise ValueError("user {} is invalid".format(id_))

            tags = self.bot.user_memory_get(id_, "tags")

        elif tag_type == "convuser":
            index_type = "user"
            [conv_id, chat_id] = id_.split("|", maxsplit=1)

            if (conv_id not in self.bot.conversations and
                    conv_id not in (self.wildcard["group"],
                                    self.wildcard["one2one"])):
                raise ValueError("conversation {} is invalid".format(conv_id))

            if (not self.bot.memory.exists(["user_data", chat_id]) and
                    chat_id != self.wildcard["user"]):
                raise ValueError("user {} is invalid".format(chat_id))

            tags_users = self.bot.conversation_memory_get(conv_id, "tags-users")

            if not tags_users:
                tags_users = {}

            if chat_id in tags_users:
                tags = tags_users[chat_id]

        else:
            raise TypeError("unhandled read tag_type {}".format(tag_type))

        if not tags:
            tags = []

        if action == "set":
            # XXX: placed here so users can still remove previous invalid tags
            allowed = "^[{}{}]*$".format(self.regex_allowed,
                                         re.escape(command.deny_prefix))
            if not re.match(allowed, tag, re.IGNORECASE):
                raise ValueError("tag contains invalid characters")

            if tag not in tags:
                tags.append(tag)
                self.add_to_index(index_type, tag, id_)
                updated = True

        elif action == "remove":
            try:
                tags.remove(tag)
                self.remove_from_index(index_type, tag, id_)
                updated = True
            except ValueError:
                # in case the value does not exist
                pass

        else:
            raise ValueError("unrecognised action {}".format(action))

        if updated:
            if tag_type == "conv":
                self.bot.conversation_memory_set(id_, "tags", tags)

            elif tag_type == "user":
                self.bot.user_memory_set(id_, "tags", tags)

            elif tag_type == "convuser":
                tags_users[chat_id] = tags
                self.bot.conversation_memory_set(conv_id, "tags-users",
                                                 tags_users)

            else:
                raise TypeError("unhandled update tag_type {}".format(tag_type))

            logger.info("%s/%s action=%s value=%s", tag_type, id_, action, tag)
        else:
            logger.info("%s/%s action=%s value=%s [NO CHANGE]", tag_type, id_,
                        action, tag)

        return updated

    def add(self, tag_type, id_, tag):
        """add tag to (tag_type=conv|user|convuser) id_"""
        return self.update(tag_type, id_, "set", tag)

    def remove(self, tag_type, id_, tag):
        """remove tag from (tag_type=conv|user|convuser) id_"""
        return self.update(tag_type, id_, "remove", tag)

    def purge(self, tag_type, id_):
        """completely remove the specified tag_type

        (tag_type="user|convuser|conv|tag|usertag|convtag") and label
        """
        remove = []

        if tag_type in ('user', 'convuser'):
            for key in self.indices["user-tags"]:

                match_user = (tag_type == "user" and id_ in (key, 'ALL'))
                # runs if tag_type=="user"

                match_convuser = (key.endswith("|" + id_)
                                  or (id_ == "ALL" and "|" in key))
                # runs if tag_type=="user" or tag_type=="convuser"

                if match_user or match_convuser:
                    for tag in self.indices["user-tags"][key]:
                        remove.append(
                            ("user" if match_user else "convuser", key, tag)
                        )

        elif tag_type == "conv":
            for key in self.indices["conv-tags"]:
                if id_ in (key, 'ALL'):
                    for tag in self.indices["conv-tags"][key]:
                        remove.append(("conv", key, tag))

        elif tag_type in ('tag', 'usertag', 'convtag'):
            if tag_type == "usertag":
                _types = ["user"]
            elif tag_type == "convtag":
                _types = ["conv"]
            else:
                # tag_type=="tag"
                _types = ["conv", "user"]

            for _type in _types:
                _index_name = "tag-{}s".format(_type)
                for tag in self.indices[_index_name]:
                    if id_ in (tag, 'ALL'):
                        for key in self.indices[_index_name][tag]:
                            remove.append((_type, key, id_))

        else:
            raise TypeError("{}".format(tag_type))

        records_removed = 0
        if remove:
            for args in remove:
                if self.remove(*args):
                    records_removed += 1

        return records_removed

    def convactive(self, conv_id):
        """return active tags for conv_id, or generic GROUP, ONE_TO_ONE keys"""

        active_tags = []
        check_keys = []

        if conv_id in self.bot.conversations:
            check_keys.extend([conv_id])
            # additional overrides based on type of conversation
            conv_type = self.bot.conversations[conv_id]["type"]
            if conv_type == "GROUP":
                check_keys.extend([self.wildcard["group"]])
            elif conv_type == "ONE_TO_ONE":
                check_keys.extend([self.wildcard["one2one"]])
            check_keys.extend([self.wildcard["conversation"]])
        else:
            logger.warning("convactive: conversation %s does not exist", conv_id)

        for _key in check_keys:
            if _key in self.indices["conv-tags"]:
                active_tags.extend(self.indices["conv-tags"][_key])
                active_tags = list(set(active_tags))
                if "tagging-merge" not in active_tags:
                    break

        return active_tags

    def useractive(self, chat_id, conv_id=None):
        """fetch active tags of user for given conversation or globally

        Args:
            chat_id (str): G+ID
            conv_id (str): a Hangout ID to fetch tags for a single conv

        Returns:
            list[str]: matching tags for user and conversation
        """
        if chat_id == "sync":
            return []

        if not self.bot.memory.exists(["user_data", chat_id]):
            logger.warning("useractive: user %s does not exist", chat_id)
            return []

        active_tags = set()
        check_keys = []

        if conv_id is not None:
            if conv_id in self.bot.conversations:
                # per_conversation_user_override_keys
                check_keys.extend([conv_id + "|" + chat_id,
                                   conv_id + "|" + self.wildcard["user"]])

                # additional overrides based on type of conversation
                if self.bot.conversations[conv_id]["type"] == "GROUP":
                    check_keys.extend([
                        self.wildcard["group"] + "|" + chat_id,
                        self.wildcard["group"] + "|" + self.wildcard["user"]])
                else:
                    check_keys.extend([
                        self.wildcard["one2one"] + "|" + chat_id,
                        self.wildcard["one2one"] + "|" + self.wildcard["user"]])

            else:
                logger.warning("useractive: conversation %s does not exist",
                               conv_id)

        check_keys.extend([chat_id, self.wildcard["user"]])

        for _key in check_keys:
            if _key in self.indices["user-tags"]:
                active_tags.update(self.indices["user-tags"][_key])
                if "tagging-merge" not in active_tags:
                    break

        return list(active_tags)

    def userlist(self, conv_id, tags=False):
        """return dict of participating chat_ids to tags

        optionally filtered by tag/list of tags
        """

        if isinstance(tags, str):
            tags = [tags]

        userlist = []
        try:
            userlist = self.bot.conversations[conv_id]["participants"]
        except KeyError:
            logger.warning("userlist: conversation %s does not exist", conv_id)

        results = {}
        for chat_id in userlist:
            user_tags = self.useractive(chat_id, conv_id)
            if tags and not set(tags).issubset(set(user_tags)):
                continue
            results[chat_id] = user_tags
        return results
