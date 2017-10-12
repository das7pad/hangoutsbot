"""
example plugin which demonstrates user and conversation memory
"""

import plugins


def _initialise():
    plugins.register_admin_command(["rememberme", "whatme", "forgetme",
                                    "rememberchat", "whatchat", "forgetchat"])


def rememberme(bot, event, *args):
    """remember value for current user, memory must be empty.
    use /bot forgetme to clear previous storage
    """

    text = bot.user_memory_get(event.user.id_.chat_id, 'test_memory')
    if text is None:
        bot.user_memory_set(
            event.user_id.chat_id, 'test_memory', ' '.join(args))
        return _("<b>{}</b>, remembered!").format(
            event.user.full_name, text)
    return _("<b>{}</b>, remembered something else!").format(
        event.user.full_name)


def whatme(bot, event, *dummys):
    """reply with value stored for current user"""

    text = bot.user_memory_get(event.user.id_.chat_id, 'test_memory')
    if text is None:
        return _("<b>{}</b>, nothing remembered!").format(
            event.user.full_name)
    return _("<b>{}</b> asked me to remember <i>\"{}\"</i>").format(
        event.user.full_name, text)


def forgetme(bot, event, *dummys):
    """forget stored value for current user"""

    text = bot.user_memory_get(event.user_id.chat_id, 'test_memory')
    if text is None:
        return _("<b>{}</b>, nothing to forget!").format(
            event.user.full_name)
    bot.user_memory_set(event.user.id_.chat_id, 'test_memory', None)
    return _("<b>{}</b>, forgotten!").format(
        event.user.full_name)


# conversation memory

def rememberchat(bot, event, *args):
    """remember value for current conversation, memory must be empty.
    use /bot forgetchat to clear previous storage
    """

    text = bot.conversation_memory_get(event.conv_id, 'test_memory')
    if text is None:
        bot.conversation_memory_set(
            event.conv_id, 'test_memory', ' '.join(args))
        return _("<b>{}</b>, remembered for this conversation").format(
            event.user.full_name, text)
    return _("<b>{}</b>, remembered something else for this conversation!"
            ).format(event.user.full_name)


def whatchat(bot, event, *dummys):
    """reply with stored value for current conversation"""

    text = bot.conversation_memory_get(event.conv_id, 'test_memory')
    if text is None:
        return _("<b>{}</b>, nothing remembered for this conversation!").format(
            event.user.full_name)
    return _("<b>{}</b> asked me to remember <i>\"{}\" for this "
             "conversation</i>").format(event.user.full_name, text)


def forgetchat(bot, event, *dummys):
    """forget stored value for current conversation"""

    text = bot.conversation_memory_get(event.conv_id, 'test_memory')
    if text is None:
        return _("<b>{}</b>, nothing to forget for this conversation!").format(
            event.user.full_name)
    bot.conversation_memory_set(event.conv_id, 'test_memory', None)
    return _("<b>{}</b>, forgotten for this conversation!").format(
        event.user.full_name)
