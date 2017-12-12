"""hangups conversation data cache"""
# pylint: disable=W0212
from datetime import datetime
import logging
import random
import re

import hangups

from hangupsbot.base_models import BotMixin

logger = logging.getLogger(__name__)

SENTINEL = object()

def name_from_hangups_conversation(conv):
    """get the name for supplied hangups conversation
    based on hangups.ui.utils.get_conv_name, except without the warnings
    """
    name = conv._conversation.name
    if isinstance(name, str) and name:
        return name

    if not conv.users:
        return "Empty Conversation"
    if conv.users == 1:
        return conv.users[0].full_name

    participants = sorted(conv.users, key=lambda user: user.id_.chat_id)
    names = [user.first_name for user in participants
             if not user.is_self]
    return ', '.join(names)

def load_missing_entrys(bot):
    """load users and conversations that are missing on bot start into hangups

    Args:
        bot: HangupsBot instance
    """
    loaded_users = bot._user_list._user_dict
    for chat_id, user_data in bot.memory["user_data"].items():
        if any((len(chat_id) != 21,
                not chat_id.isdigit(),
                not isinstance(user_data, dict),
                '_hangups' not in user_data)):
            continue
        user_id = hangups.user.UserID(chat_id=chat_id, gaia_id=chat_id)
        if user_id in loaded_users:
            continue
        user = hangups.user.User(user_id, user_data["_hangups"]["full_name"],
                                 user_data["_hangups"]["first_name"],
                                 user_data["_hangups"]["photo_url"],
                                 user_data["_hangups"]["emails"], False)
        loaded_users[user_id] = user

    for conv_id in bot.conversations:
        bot.get_conversation(conv_id)

async def initialise(bot):
    """load cache from memory and update it with new data from hangups

    Args:
        bot: HangupsBot instance

    Returns:
        ConversationMemory instance
    """
    permamem = ConversationMemory()

    permamem.standardise_memory()
    await permamem.load_from_hangups()
    await permamem.load_from_memory()

    # set the attribute here as a HangupsConversation might needs to access it
    bot.conversations = permamem
    load_missing_entrys(bot)

    permamem.stats()

    bot.memory.save()
    return permamem


class ConversationMemory(BotMixin):
    """cache conversation data that might be missing on bot start

    Args:
        bot: HangupsBot instance
    """
    def __init__(self):
        self.catalog = {}

        self.bot.memory.on_reload.add_observer(self.standardise_memory)
        self.bot.memory.on_reload.add_observer(self.load_from_memory)

    def __del__(self):
        """explicit cleanup"""
        self.bot.memory.on_reload.remove_observer(self.standardise_memory)
        self.bot.memory.on_reload.remove_observer(self.load_from_memory)

    def stats(self):
        """log meta of the permamem"""
        logger.info("total conversations: %s", len(self.catalog))

        count_user = 0
        count_user_definitive = 0
        for chat_id in self.bot.memory["user_data"]:
            if "_hangups" not in self.bot.memory["user_data"][chat_id]:
                continue
            count_user = count_user + 1
            if (self.bot.memory["user_data"][chat_id]["_hangups"]
                    ["is_definitive"]):
                count_user_definitive += 1

        logger.info("total users: %s | definitive at start: %s",
                    count_user, count_user_definitive)

    def standardise_memory(self):
        """ensure the latest conversation memory structure

        migrate new keys, also add to attribute change checks in .update()
        """
        if not self.bot.memory.exists(['convmem']):
            self.bot.memory.set_by_path(['convmem'], {})
            return

        convs = self.bot.memory.get_by_path(['convmem'])
        for conv_id, conv in convs.items():
            # remove obsolete users list
            if "users" in conv:
                del conv["users"]

            conv.setdefault("type", "unknown")
            conv.setdefault("history", True)
            conv.setdefault("participants", [])
            conv.setdefault("link_sharing", False)
            conv.setdefault("status", "DEFAULT")

            if conv["type"] != "unknown":
                continue

            # guess the type
            conv["type"] = "GROUP"
            if len(conv["participants"]) != 1:
                continue

            path = ["user_data", conv["participants"][0], "1on1"]
            if (self.bot.memory.exists(path)
                    and self.bot.get_by_path(path) == conv_id):
                conv["type"] = "ONE_TO_ONE"

    async def load_from_memory(self):
        """load "persisted" conversations from memory.json into self.catalog
        complete internal user list by using "participants" keys
        """

        convs = self.bot.memory.get_by_path(['convmem'])
        logger.debug("loading %s conversations from memory", len(convs))

        _users_added = {}
        _users_incomplete = {}
        _users_unknown = []

        _users_to_fetch = []

        for convid, conv in convs.items():
            self.catalog[convid] = conv
            for chat_id in conv["participants"]:
                try:
                    userid = hangups.user.UserID(chat_id=chat_id,
                                                 gaia_id=chat_id)
                    user = self.bot._user_list._user_dict[userid]
                    results = self.store_user_memory(user)
                    if results:
                        _users_added[chat_id] = user.full_name

                except KeyError:
                    cached = self.bot.user_memory_get(chat_id, "_hangups")
                    if cached is not None:
                        if cached["is_definitive"]:
                            continue
                        _users_incomplete[chat_id] = cached["full_name"]
                    else:
                        _users_unknown.append(chat_id)

                    _users_to_fetch.append(chat_id)

        if _users_added:
            logger.info("added users: %s", _users_added)

        if _users_incomplete:
            logger.info("incomplete users: %s", _users_incomplete)

        if _users_unknown:
            logger.warning("unknown users: %s", _users_unknown)

        if _users_to_fetch:
            await self.get_users_from_query(_users_to_fetch)

    async def load_from_hangups(self):
        """update the permamem from the user- and conv list of hangups"""
        users = self.bot._user_list.get_all()
        logger.info("loading %s users from hangups", len(users))
        for user in users:
            self.store_user_memory(user)

        conversations = self.bot._conv_list.get_all()
        logger.info("loading %s conversations from hangups", len(conversations))
        for conversation in conversations:
            await self.update(conversation, source="init", automatic_save=False)

    async def get_users_from_query(self, chat_ids):
        """retrieve definitive user data by requesting it from the server

        Args:
            chat_ids: list of string, a list of G+ ids

        Returns:
            integer, number of updated users
        """

        chat_ids = list(set(chat_ids))

        updated_users = 0
        logger.debug("getentitybyid(): %s", chat_ids)

        request = hangups.hangouts_pb2.GetEntityByIdRequest(
            request_header=self.bot.get_request_header(),
            batch_lookup_spec=[
                hangups.hangouts_pb2.EntityLookupSpec(gaia_id=chat_id)
                for chat_id in chat_ids])
        try:
            response = await self.bot.get_entity_by_id(request)
        except hangups.exceptions.NetworkError:
            logger.exception("getentitybyid(): FAILED for %s", chat_ids)
            return 0

        for entity in response.entity:
            user = hangups.user.User.from_entity(entity, False)
            self.bot._user_list._user_dict[user.id_] = user

            if self.store_user_memory(user):
                updated_users += 1
        self.bot.memory.save()

        if updated_users:
            logger.info("getentitybyid(): %s users updated", updated_users)
        return updated_users

    def store_user_memory(self, user):
        """update user memory based on supplied hangups User

        Args:
            user: hangups.user.User instance

        Returns:
            boolean, True if the permamem entry for the user changed
        """
        is_definitive = user.name_type == hangups.user.NameType.DEFAULT

        # reject an update if a valid user would be overwritten by a default one
        cached = self.bot.user_memory_get(user.id_.chat_id, "_hangups") or {}
        if cached and cached.get("is_definitive", 0) > is_definitive:
            return False

        user_dict = {
            "chat_id": user.id_.chat_id,
            "full_name": user.full_name,
            "first_name": user.first_name,
            "photo_url": user.photo_url,
            "emails": list(user.emails),
            "is_self": user.is_self,
            "is_definitive": is_definitive,
        }

        changed = True
        if cached:
            try:
                for key in user_dict:
                    assert user_dict[key] == cached[key]
            except AssertionError:
                message = "user %s changed for %s (%s)"
            except KeyError:
                message = "user %s missing for %s (%s)"
            else:
                message = None
                changed = False
        else:
            message = "%snew user %s (%s)"
            key = ''

        if changed:
            logger.info(message, key, user.full_name, user.id_.chat_id)
            user_dict["updated"] = datetime.now().strftime("%Y%m%d%H%M%S")
            self.bot.user_memory_set(user.id_.chat_id, "_hangups", user_dict)
        return changed

    async def update(self, conv, source="unknown", automatic_save=True):
        """update conversation memory based on supplied hangups Conversation

        Args:
            conv: hangups.conversation.Conversation instance
            source: string, origin of the conv, 'event', 'init'
            automatic_save: boolean, toggle to dump the memory on changes

        Returns:
            boolean, True on Conversation/User change, False on no changes
        """
        _conversation = conv._conversation
        conv_title = name_from_hangups_conversation(conv)

        cached = (self.bot.memory.get_by_path(["convmem", conv.id_])
                  if self.bot.memory.exists(["convmem", conv.id_]) else {})

        memory = {
            "title": conv_title,
            "source": source,
            "history": not conv.is_off_the_record,
            "participants": [],
            "type": ("GROUP" if _conversation.type
                     == hangups.hangouts_pb2.CONVERSATION_TYPE_GROUP
                     else "ONE_TO_ONE"),
            "status": ("INVITED" if _conversation.self_conversation_state.status
                       == hangups.hangouts_pb2.CONVERSATION_STATUS_INVITED
                       else "DEFAULT"),
            "link_sharing": (_conversation.group_link_sharing_status ==
                             hangups.hangouts_pb2.GROUP_LINK_SHARING_STATUS_ON)
        }

        _users_to_fetch = [] # track unknown users from hangups Conversation
        users_changed = False # track whether memory["user_data"] was changed

        for user in conv.users:
            if not user.is_self:
                memory["participants"].append(user.id_.chat_id)

            if user.name_type == hangups.user.NameType.DEFAULT:
                _users_to_fetch.append(user.id_.chat_id)

            users_changed = self.store_user_memory(user) or users_changed

        if _users_to_fetch:
            logger.info("unknown users returned from %s (%s): %s",
                        conv_title, conv.id_, _users_to_fetch)
            await self.get_users_from_query(_users_to_fetch)

        conv_changed = True
        if cached:
            memory["participants"].sort()
            cached["participants"].sort()
            try:
                for key in memory:
                    assert key == 'source' or memory[key] == cached[key]
            except AssertionError:
                message = "conv %s changed for %s (%s)"
            except KeyError:
                message = "conv %s missing for %s (%s)"
            else:
                message = None
                conv_changed = False
        else:
            message = "%snew conv %s (%s)"
            key = ''

        if conv_changed:
            logger.info(message, key, conv_title, conv.id_)
            memory["updated"] = datetime.now().strftime("%Y%m%d%H%M%S")
            self.bot.memory.set_by_path(["convmem", conv.id_], memory)

            self.catalog[conv.id_] = memory

        if automatic_save:
            self.bot.memory.save()

        return conv_changed or users_changed


    def remove(self, conv_id):
        """remove the permamem entry of a given conversation

        Args:
            conv_id: string, hangouts conversation identifier
        """
        if self.bot.memory.exists(["convmem", conv_id]):
            cached = self.bot.memory.get_by_path(["convmem", conv_id])
            if cached["type"] == "GROUP":
                logger.info("removing conv: %s %s", conv_id, cached["title"])
                self.bot.memory.pop_by_path(["convmem", conv_id])
                self.bot.memory.save()
                del self.catalog[conv_id]

            else:
                logger.warning("cannot remove conv: %s %s %s",
                               cached["type"], conv_id, cached["title"])

        else:
            logger.warning("cannot remove: %s, not found", conv_id)

    def get(self, search="", **kwargs):          #pylint:disable=too-many-locals
        """get conversations matching a filter of terms

        supports sequential boolean operations,
        each term must be enclosed with brackets "( ... )"

        Args:
            search: string, filter for conv title, id, tags, type, user count
            kwargs: dict, legacy to catch the keyword argument 'filter'

        Returns:
            dict, conv ids as keys and permamem entry of each conv as value
        """
        def parse_request(locals_):
            """split multiple querys to their filter functions and queryvalue

            Args:
                locals_: dict, locals of .get to access all filter functions

            Returns:
                list, a list of tuple,
                (operator : string, query: string, <filter func> : callable)
                invalid filter querys result in a string as filter func
            """
            raw_filter = (kwargs.get('filter') or search).strip()
            terms = []
            operator = "start"
            while raw_filter.startswith("("):
                tokens = re.split(r"(?<!\\)(?:\\\\)*\)", raw_filter, maxsplit=1)
                terms.append((operator, tokens[0][1:]))
                if len(tokens) != 2:
                    break
                raw_filter = tokens[1]
                if not raw_filter:
                    # finished consuming entire string
                    pass
                elif re.match(r"^\s*and\s*\(", raw_filter, re.IGNORECASE):
                    operator = "and"
                    raw_filter = tokens[1][raw_filter.index('('):].strip()
                elif re.match(r"^\s*or\s*\(", raw_filter, re.IGNORECASE):
                    operator = "or"
                    raw_filter = tokens[1][raw_filter.index('('):].strip()
                else:
                    raise ValueError('invalid boolean operator near "%s"' %
                                     raw_filter.strip())

            if raw_filter or not terms:
                # second condition is to ensure at least one term, even if blank
                terms.append((operator, raw_filter))

            logger.debug(".get() with terms: %s", terms)

            parsed = []
            for operator, term in terms:
                if ":" in term:
                    type_, query = term.split(":", 1)
                    parsed.append((operator, query, locals_.get("_" + type_,
                                                                type_)))
                else:
                    parsed.append((operator, term, _id))
            return parsed

        #### begin search function definitions ###
        # NOTE: more filter can be added here
        # a search for "querytype:queryvalue" requires a function with a
        # footprint like: _querytype(convid, convdata, queryvalue)
        def _text(dummy0, convdata, query):
            """check the conv title for the given query

            Returns:
                boolean, True if the query is part of the title otherwise False
            """
            query = query.lower()
            return (query in convdata["title"].lower()
                    or query in convdata["title"].replace(" ", "").lower())

        def _id(convid, dummy0, query):
            """check if the query matches with the convid

            Returns:
                boolean, True if the convid and query match otherwise False
            """
            return convid == query

        def _chat_id(dummy0, convdata, query):
            """check the user chat ids for a match with the query

            Returns:
                boolean, True if any chat_id matches the query, otherwise False
            """
            for chat_id in convdata["participants"]:
                if query == chat_id:
                    return True

        def _type(dummy0, convdata, query):
            """check if the conversation type matches with the query

            Returns:
                boolean, True if the type matches otherwise False
            """
            return convdata["type"] == query.upper()

        def _minusers(dummy0, convdata, query):
            """check if the user count of a conv is not below the query value

            Returns:
                boolean, False if fewer users are in the conv, otherwise True
            """
            return len(convdata["participants"]) >= int(query)

        def _maxusers(dummy0, convdata, query):
            """check if the user count of a conv is not above the query value

            Returns:
                boolean, False if more users are in the conv, otherwise True
            """
            return len(convdata["participants"]) <= int(query)

        def _random(dummy0, dummy1, query):
            """check the query value against a random number between 0 and 1

            Returns:
                boolean, True if the query value is greater, otherwise False
            """
            return random.random() < float(query)

        def _tag(convid, dummy0, query):
            """check if the query is a registered tag and the conv is tagged

            Returns:
                boolean, True if the query is a tag and the conv is tagged w/ it
            """
            return (query in self.bot.tags.indices["tag-convs"] and
                    convid in self.bot.tags.indices["tag-convs"][query])

        ### end search function definitions ###
        sourcelist = self.catalog.copy()
        matched = {}

        for operator, query, func in parse_request(locals()):
            if not callable(func):
                logger.warning('ConversationMemory.get: invalid filter "%s:%s"',
                               func, query)
                continue

            if operator == "and":
                sourcelist = matched
                matched = {}

            if not query:
                # return everything
                matched = sourcelist
                continue

            for convid, convdata in sourcelist.items():
                if func(convid, convdata, query):
                    matched[convid] = convdata
        return matched

    def get_name(self, conv, fallback=SENTINEL):
        """get the name of a conversation

        Args:
            conv: string or hangups.conversation.Conversation instance
            fallback: any type, a fallback if no name is available

        Returns:
            string, a conversation name or the fallback if no name is available

        Raises:
            ValueError: no name is available but no fallback was specified
        """
        if isinstance(conv, str):
            convid = conv
        else:
            convid = conv.id_

        try:
            return self.catalog[convid]["title"]
        except KeyError:
            if not isinstance(conv, str):
                return name_from_hangups_conversation(conv)

            if fallback is SENTINEL:
                raise ValueError("could not determine conversation name")

            return fallback

    def __iter__(self):
        return iter(self.catalog)

    def __getitem__(self, key):
        return self.catalog[key]

    def __setitem__(self, key, value):
        self.catalog[key] = value

    def __delitem__(self, key):
        del self.catalog[key]

    def __len__(self):
        return len(self.catalog)
