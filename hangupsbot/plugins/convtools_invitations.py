import asyncio
import datetime
import logging
import random
import string
import time

import hangups

from hangupsbot import plugins
from hangupsbot.commands import (
    Help,
    command,
)


logger = logging.getLogger(__name__)

# TODO(das7pad) rewrite needed - can be merged with other plugins
# TODO(das7pad) add a command to remove expired invites (from memory)

HELP = {
    "invite": _('manage invite for users:\n"list", "purge" allows listing and '
                'removing invites - add "expired" to view inactive invites\n'
                '"from" specifies users from source conversation id - if unset,'
                'gets users from current group or list of "users"\n"to" '
                'specifies destination conversation id - if unset, uses current'
                'group or creates a new one\n"test" to prevent writing anything'
                'to storage'),

    "rsvp": _("show invite codes or claim an invite"),
}

EXPIRE_IN = 2592000

class DummyEvent:
    """used to run the rename command"""
    pass

def _initialise():
    """register commands and the help entries"""
    plugins.register_admin_command(["invite"])
    plugins.register_user_command(["rsvp"])
    plugins.register_handler(_issue_invite_on_exit, "membership")
    plugins.register_help(HELP)


def _remove_invite(bot, invite_code):
    memory_path = ["invites", invite_code]
    if bot.memory.exists(memory_path):
        popped_invitation = bot.memory.pop_by_path(memory_path)
        bot.memory.save()
        logger.debug("_remove_invite: %s", popped_invitation)
    else:
        logger.debug("_remove_invite: nothing removed")


def _issue_invite(bot, user_id, group_id, uses=1):
    if not bot.memory.exists(["invites"]):
        bot.memory["invites"] = {}

    invitation = False

    # find existing unexpired invitation by user and group - exact match only
    for _key, _invitation in bot.memory["invites"].items():
        if _invitation["user_id"] == user_id and _invitation["group_id"] == group_id and _invitation["expiry"] > time.time():
            invitation = _invitation
            logger.debug("_issue_invite: found existing invite id: %s",
                         invitation["id"])
            break

    # create new invitation if no match found
    if not invitation:
        while True:
            _id = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(6))
            if _id not in bot.memory["invites"]:
                logger.debug("_issue_invite: create new invite id: %s", _id)
                invitation = {
                    "id": _id,
                    "user_id": user_id,
                    "group_id": group_id
                }
                break

    if not invitation:
        raise ValueError("no invitation")

    # update/create some fields
    invitation["expiry"] = int(time.time()) + EXPIRE_IN
    invitation["uses"] = uses
    invitation["updated"] = time.time()

    # write to user memory
    bot.memory["invites"][invitation["id"]] = invitation
    bot.memory.save()

    return invitation["id"]


async def _claim_invite(bot, invite_code, user_id):
    memory_path = ["invites", invite_code]

    if not bot.memory.exists(memory_path):
        return

    invitation = bot.memory.get_by_path(memory_path)
    if invitation["user_id"] in ("*", user_id) and invitation["expiry"] > time.time():
        conv_id = invitation["group_id"]
        logger.debug("_claim_invite: adding %s to %s",
                     user_id, conv_id)
        conv = bot.get_conversation(conv_id)
        try:
            await conv.add_users(
                hangups.user.UserID(chat_id=user_id, gaia_id=user_id))

        except hangups.NetworkError:
            logger.exception("_CLAIM_INVITE: FAILED %s %s",
                             invite_code, user_id)
            return

        invitation["uses"] -= 1

        if invitation["uses"]:
            bot.memory.set_by_path(memory_path, invitation)
            bot.memory.save()
        else:
            _remove_invite(bot, invite_code)

        logger.debug("_claim_invite: claimed %s", invitation)

    else:
        logger.debug("_claim_invite: invalid")


def _issue_invite_on_exit(bot, event):
    # Check if issue_invite_on_exit is disabled
    if bot.get_config_suboption(event.conv_id, 'disable_invites_on_exit'):
        return

    if event.conv_event.type_ == hangups.MEMBERSHIP_CHANGE_TYPE_LEAVE:
        event_users = [event.conv.get_user(user_id) for user_id
                       in event.conv_event.participant_ids]
        users_leaving = [user.id_.chat_id for user in event_users]
        for uid in users_leaving:
            _issue_invite(bot, uid, event.conv_id)


async def _new_group_conversation(bot, initiator_id):
    # pylint:disable=protected-access
    _response = await bot._client.create_conversation(
        hangups.hangouts_pb2.CreateConversationRequest(
            request_header=bot._client.get_request_header(),
            type=hangups.hangouts_pb2.CONVERSATION_TYPE_GROUP,
            client_generated_id=bot._client.get_client_generated_id(),
            invitee_id=[hangups.hangouts_pb2.InviteeID(gaia_id=initiator_id)]))
    # pylint:enable=protected-access
    new_conversation_id = _response.conversation.conversation_id.id

    await bot.coro_send_message(new_conversation_id, _("<i>group created</i>"))
    await asyncio.sleep(1) # allow convmem to update
    name = _("GROUP: %s") % datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    await command.run(
        bot, DummyEvent(), *["convrename", "id:" + new_conversation_id, name])
    return new_conversation_id


def _get_invites(bot, filter_active=True, filter_user=False):
    invites = {}
    if bot.memory.exists(["invites"]):
        for invite_id, invite_data in bot.memory["invites"].items():
            if filter_active and time.time() > invite_data["expiry"]:
                continue
            if not filter_active and time.time() < invite_data["expiry"]:
                continue
            if filter_user and invite_data["user_id"] not in ("*", filter_user):
                continue
            invites[invite_id] = invite_data
    return invites


def _get_user_list(bot, conv_id):
    permamem_conv = bot.conversations.get(conv_id)
    return permamem_conv[conv_id]["participants"]


async def invite(bot, event, *args):
    """add in one handler for getting users into conversations

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): additional words to form the request

    Returns:
        str: command output

    Raises:
        Help: invalid query specified
    """
    test = False

    everyone = True
    wildcards = 0

    target_conv = False
    source_conv = False
    list_users = []

    # special cases:
    # * test [set flag, then remove parameter]
    # * no parameters [error out]
    # * 1st parameter is digit [wildcard invite]
    # * any parameter is "list" or "purge" [process then return immediately]

    parameters = list(args)

    if "test" in parameters:
        # turn on test mode - prevents writes
        test = True
        parameters.remove("test")

    if not parameters:
        return _("<em>insufficient parameters for invite</em>")

    if parameters[0].isdigit():
        # wildcard invites can be used by any user with access to the bot
        # note: wildcard invite command can still be superseded by specifying a "users" list
        #   as a parameter
        wildcards = int(parameters[0])
        if wildcards and wildcards < 150:
            del parameters[0]

    elif "list" in parameters or "purge" in parameters:
        # [list] all invites inside the bot memory, and [purge] when requested

        lines = []

        if "purge" in parameters:
            if test:
                lines.append(_("<b>Test Invitation Purge</b>"))
            else:
                lines.append(_("<b>Invitation Purge</b>"))
            _mode = "purge"
        else:
            lines.append(_("<b>Invitation List</b>"))
            _mode = "list"

        if "expired" in parameters:
            _active_only = False
        else:
            _active_only = True

        active_invites = _get_invites(bot, filter_active=_active_only)

        if active_invites:
            for _id, data in active_invites.items():
                try:
                    conversation_name = bot.conversations.get_name(data["group_id"])
                except ValueError:
                    conversation_name = "? ({})".format(data["group_id"])

                user_id = data["user_id"]
                if user_id == "*":
                    user_id = "anyone"

                if not test and _mode == "purge":
                    _remove_invite(bot, data["id"])

                expiry_in_days = round((data["expiry"] - time.time()) / 86400, 1)
                lines.append("<i><pre>{}</pre></i> to <b><pre>{}</pre></b> ... {} ({} days left)".format(
                    user_id, conversation_name, data["id"], expiry_in_days))

        else:
            lines.append(_("<em>no invites found</em>"))

        return "\n".join(lines)

    # process parameters sequentially using a finite state machine

    state = ["users"]
    for parameter in parameters:
        if parameter in ("to", "from", "users"):
            state.append(parameter)
        else:
            if state[-1] == "to":
                target_conv = parameter
                state.pop()
            elif state[-1] == "from":
                source_conv = parameter
                state.pop()
            elif state[-1] == "users":
                list_users.append(parameter)
                everyone = False # filter invitees by list_users
                wildcards = 0 # turn off wildcard invites
            else:
                raise Help("UNKNOWN STATE: {}".format(state[-1]))

    # ensure supplied conversations are consistent

    if not target_conv and not source_conv:
        # from = None, to = None:
        #     source_conv = current
        #     target_conv = new blank conversation
        source_conv = event.conv_id
        target_conv = "NEW_GROUP"

    elif not target_conv:
        # from = current, to = None:
        #     source_conv = current
        #     target_conv = new blank conversation
        # from = other, to = None:
        #     source_conv = other
        #     target_conv = current (or new, if not GROUP)
        if source_conv == event.conv_id:
            target_conv = "NEW GROUP"
        else:
            if bot.conversations[event.conv_id]["type"] != "GROUP":
                target_conv = "NEW_GROUP"
            else:
                target_conv = event.conv_id

    elif not source_conv:
        # list_users = 0:
        #     from = None, to = current:
        #         ERROR
        #     from = None, to = other:
        #         source_conv = current
        #         target_conv = other
        # list_users > 0:
        #     source_conv = None
        #     target_conv = *
        if not list_users:
            if target_conv == event.conv_id:
                return _('<em>invite: specify "from" or explicit list of "users"</em>')
            source_conv = event.conv_id

    # sanity checking

    if target_conv != "NEW_GROUP" and target_conv not in bot.conversations.get():
        return _('<em>invite: could not identify target conversation')

    # invitation generation

    invitation_log = [] # dev note: no more returns after this line!

    invitation_log.append("source conv: {}, target conv: {}".format(source_conv, target_conv))
    invitation_log.append("user list = [{}]".format(len(list_users)))

    invitations = []

    if wildcards:
        # wildcards can be used by any user to enter a target_conv
        invitations.append({
            "user_id": "*",
            "uses": wildcards})

        invitation_log.append("wildcard invites: {}".format(wildcards))
        logger.info("convtools_invitations: %s wildcard invite for %s",
                    wildcards, target_conv)

    else:
        # shortlist users from source room, or explicit list_users
        shortlisted = []
        if source_conv:
            source_conv_users = _get_user_list(bot, source_conv)
            for chat_id in source_conv_users:
                if everyone or chat_id in list_users:
                    shortlisted.append(chat_id)

            invitation_log.append("shortlisted: {}/{}".format(len(shortlisted), len(source_conv_users)))
            logger.info("convtools_invitations: shortlisted %s/%s from %s, "
                        "everyone=%s, list_users=[%s]",
                        len(shortlisted), len(source_conv_users),
                        source_conv, everyone, len(list_users))

        else:
            shortlisted = list_users

            invitation_log.append("direct list: {}".format(len(shortlisted)))
            logger.info("%s convtools_invitations: shortlisted %s",
                        len(shortlisted), source_conv)

        # exclude users who are already in the target conversation
        if target_conv == "NEW_GROUP":
            # fake user list - _new_group_conversation() always creates group with bot and initiator
            target_conv_users = [event.user.id_.chat_id, bot.user_self()["chat_id"]]
        else:
            target_conv_users = _get_user_list(bot, target_conv)
        invited_users = []
        for uid in shortlisted:
            if uid not in target_conv_users:
                invited_users.append(uid)
            else:
                invitation_log.append("excluding existing: {}".format(uid))
                logger.info(
                    "convtools_invitations: rejecting %s, already in %s",
                    uid, target_conv)
        invited_users = list(set(invited_users))

        logger.info("convtools_invitations: inviting %s to %s",
                    len(invited_users), target_conv)

        for uid in invited_users:
            invitations.append({
                "user_id": uid,
                "uses": 1})

    # beyond this point, start doing irreversible things (like create groups)

    if not invitations:
        invitation_log.append("no invitations were created")
        logger.info("convtools_invitations: nobody invited, aborting...")

        return _('<em>invite: nobody invited</em>')

    # create new conversation (if required)

    if target_conv == "NEW_GROUP":
        invitation_log.append("create new group")
        if not test:
            target_conv = await _new_group_conversation(bot, event.user.id_.chat_id)

    # issue the invites

    invitation_ids = []
    for new_invite in invitations:
        invitation_log.append("invite {} to {}, uses: {}".format(
            new_invite["user_id"], target_conv, new_invite["uses"]))
        if not test:
            # invites are not created in test mode
            invitation_ids.append(
                _issue_invite(bot, new_invite["user_id"], target_conv, new_invite["uses"]))

    if invitation_ids:
        await bot.coro_send_message(
            event.conv_id,
            _("<em>invite: {} invitations created</em>").format(len(invitation_ids)))

    if test:
        invitation_log.insert(0, "<b>Invite Test Mode</b>")
        await bot.coro_send_message(event.conv_id, "\n".join(invitation_log))


async def rsvp(bot, event, *args):
    """claim an invite code or show pending invites

    Args:
        bot (hangupsbot.core.HangupsBot): the running instance
        event (hangupsbot.event.ConversationEvent): a message container
        args (str): additional words passed to the command

    Returns:
        str: command output
    """
    if len(args) == 1:
        await _claim_invite(bot, args[0], event.user.id_.chat_id)
        return

    active_invites = _get_invites(bot, filter_user=event.user_id.chat_id,
                                  filter_active=True)

    if not active_invites:
        return _("<i>no invites to display</i>")

    lines = [_("<b>Invites for {}:</b>").format(event.user.full_name)]

    for _id, _invite in active_invites.items():
        conversation_name = bot.conversations.get_name(_invite["group_id"])
        expiry_in_days = round((_invite["expiry"] - time.time()) / 86400, 1)
        lines.append(_("<b>{}</b> ... {} ({} days left)").format(
            conversation_name, _invite["id"], expiry_in_days))

    lines.append(_("<i>To claim an invite, use the rsvp command followed by"
                   "the invite code</i>"))
    return "\n".join(lines)
