"""arguments parser for inline requests"""

import re

from hangupsbot.base_models import BotMixin


class ArgumentsParser(BotMixin):
    """resolve `#` and `@` tagged arguments to `chat_id`s and `conversation_id`s

    * one_chat_id (also resolves #conv)
      * @user
      * #conv|@user (tagset convuser format)
      * abcd|@user (tagset convuser format)
    * one_conv_id
      * #conv
      * #conv|* (tagset convuser format)
      * #conv|123 (tagset convuser format)
    * test cases that won't match:
      * #abcd#
      * ##abcd
      * ##abcd##
      * ##abcd|*
      * @user|abcd
      * wxyz@user
      * @user@wxyz
    """
    def __init__(self):
        self._tracking = None
        self._preprocessors = {
            "inbuilt": {
                r"^(#?[\w|]+[^#]\|)?@[\w]+[^@]$": self._one_chat_id,
                r"^#[\w|]+[^#]$": self._one_conv_id,
            },

        }

    def set_tracking(self, tracking):
        """register the plugin tracking for commands

        Args:
            tracking (hangupsbot.plugins.Tracker): the current instance
        """
        self._tracking = tracking

    def register_preprocessor_group(self, name, preprocessors):
        name_lower = name.lower()
        self._preprocessors[name_lower] = preprocessors
        self._tracking.register_command_argument_preprocessors_group(
            name_lower)

    def deregister_preprocessor_group(self, name):
        name_lower = name.lower()
        self._preprocessors.pop(name_lower)

    def _one_chat_id(self, token, event, all_users=False):
        subtokens = token.split("|", 1)

        if subtokens[0].startswith("#"):
            # probably convuser format - resolve conversation id first
            subtokens[0] = self._one_conv_id(subtokens[0], event)

        text = subtokens[-1][1:]

        if text == "me":
            # current user chat_id
            subtokens[-1] = event.user.id_.chat_id
        else:
            user_memory = self.bot.memory["user_data"]
            chat_ids = (list(self.bot.conversations[event.conv_id]
                             ["participants"])
                        if all_users else list(user_memory.keys()))

            matched_users = {}
            for chat_id in chat_ids:
                user_data = user_memory[chat_id]
                nickname_lower = (user_data["nickname"].lower()
                                  if "nickname" in user_data else "")
                fullname_lower = user_data["_hangups"]["full_name"].lower()

                if text == nickname_lower:
                    matched_users[chat_id] = chat_id
                    break

                elif (text in fullname_lower or
                      text in fullname_lower.replace(" ", "")):
                    matched_users[chat_id] = chat_id

            if len(matched_users) == 1:
                subtokens[-1] = list(matched_users)[0]
            elif not matched_users:
                if not all_users:
                    # redo the user search, expanded to all users
                    # since this is calling itself again,
                    # completely overwrite subtokens
                    subtokens = self._one_chat_id(
                        token,
                        event,
                        all_users=True).split("|", 1)
                else:
                    raise ValueError("{} returned no users".format(token))
            else:
                raise ValueError("{} returned more than one user".format(token))

        return "|".join(subtokens)

    def _one_conv_id(self, token, event):
        subtokens = token.split("|", 1)

        text = subtokens[0][1:]
        if text == "here":
            # current conversation id
            subtokens[0] = event.conv_id
        else:
            filter_ = "(type:GROUP)and(text:{})".format(text)
            conv_list = self.bot.conversations.get(filter_)
            if len(conv_list) == 1:
                subtokens[0] = next(iter(conv_list))
            elif not conv_list:
                raise ValueError("{} returned no conversations".format(token))
            else:
                raise ValueError("{} returned too many conversations".format(
                    token))

        return "|".join(subtokens)

    def process(self, args, event, force_trigger="", force_groups=()):
        """custom preprocessing for use by other plugins, specify:
        * force_trigger word to override config, default
          prevents confusion if botmin has overridden this for their own usage
        * force_groups to a list of resolver group names
          at least 1 must exist, otherwise all resolvers will be used (as usual)
        """
        all_groups = list(self._preprocessors.keys())
        force_groups = [g for g in force_groups if g in all_groups]
        all_groups = force_groups or all_groups

        _implicit = (bool(force_groups)
                     or not self.bot.config.get_option(
                         "commands.preprocessor.explicit"))
        _trigger = (force_trigger
                    or self.bot.config.get_option(
                        "commands.preprocessor.trigger")
                    or "resolve").lower()

        _trigger_on = "+" + _trigger
        _trigger_off = "-" + _trigger
        _separator = ":"

        # simple finite state machine parser:

        # * arguments are processed in order of input, from left-to-right
        # * default setting is always post-process
        #   * switch off with config.json: commands.preprocessor.explicit = true
        # * default base trigger keyword = "resolve"
        #   * override with config.json: commands.preprocessor.trigger
        #   * full trigger keywords are:
        #     * +<trigger> (add)
        #     * -<trigger> (remove)
        #   * customised trigger word must be unique enough to prevent conflicts for other plugin parameters
        #   * all examples here assume the trigger keyword is the default
        #   * devs: if conflict arises, other plugins have higher priority than this
        # * activate all resolvers for subsequent keywords (not required if implicit):
        #     +resolve
        # * deactivate all resolvers for subsequent keywords:
        #     -resolve
        # * activate specific resolver groups via keyword:
        #     +resolve:<comma-separated list of resolver groups, no spaces> e.g.
        #     +resolve:inbuilt,customalias1,customalias2
        # * deactivate all active resolvers via keyword:
        #     +resolve:off
        #     +resolve:false
        #     +resolve:0
        # * deactivate specific resolvers via keyword:
        #     -resolve:inbuilt
        #     -resolve:inbuilt,customa
        # * escape trigger keyword with:
        #   * quotes
        #       "+resolve"
        #   * backslash
        #       \+resolve

        if "inbuilt" in all_groups:
            # lowest priority: inbuilt
            all_groups.remove("inbuilt")
            all_groups.append("inbuilt")

        if _implicit:
            # always-on
            default_groups = all_groups
        else:
            # on-demand
            default_groups = []

        apply_resolvers = default_groups
        new_args = []
        for arg in args:
            arg_lower = arg.lower()
            skip_arg = False
            if _trigger_on == arg_lower:
                # explicitly turn on all resolvers
                #   +resolve
                apply_resolvers = all_groups
                skip_arg = True
            elif _trigger_off == arg_lower:
                # explicitly turn off all resolvers
                #   -resolve
                apply_resolvers = []
                skip_arg = True
            elif arg_lower.startswith(_trigger_on + _separator):
                _right = arg_lower.split(_separator, 1)[-1]
                if not _right or _right in ("off", "false", "0"):
                    # turn off all resolver groups
                    #   +resolve:off
                    #   +resolve:false
                    #   +resolve:0
                    #   +resolve:
                    apply_resolvers = []
                elif _right == "*":
                    # turn on all resolver groups
                    #   +resolve:*
                    apply_resolvers = all_groups
                else:
                    # turn on specific resolver groups
                    #   +resolve:inbuilt
                    #   +resolve:inbuilt,customa,customb
                    apply_resolvers = _right.split(",")
                skip_arg = True
            elif arg_lower.startswith(_trigger_off + _separator):
                _right = arg_lower.split(_separator, 1)[-1]
                if not _right or _right in "*":
                    # turn off all resolver groups
                    #   -resolve:*
                    #   -resolve:
                    apply_resolvers = []
                else:
                    # turn off specific groups:
                    #   -resolve:inbuilt
                    #   -resolve:customa,customb
                    for _group in _right.split(","):
                        apply_resolvers.remove(_group)
                skip_arg = True
            if skip_arg:
                # never consume the trigger term
                continue
            for rname in [rname
                          for rname in apply_resolvers
                          if rname in all_groups]:
                for pattern, callee in self._preprocessors[rname].items():
                    if re.match(pattern, arg, flags=re.IGNORECASE):
                        _arg = callee(arg, event)
                        if _arg:
                            arg = _arg
                            continue
            new_args.append(arg)

        return new_args

def _initialize(bot):
    """register the arguments parser as shared

    Args:
        bot (HangupsBot): the running instance
    """
    from hangupsbot.commands import command
    bot.register_shared('arguments_parser', command.arguments_parser)
