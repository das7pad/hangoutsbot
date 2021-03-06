from hangupsbot import plugins


_VERIFY_TEXT = _('<i>User must say "hi" to me first via a 1-on-1 hangout, open '
                 '{url} and send me <b>{bot_cmd} verifyme</b>.</i>')

HELP = {
    'iamspartacus': _('announce to the bot that you are spartacus aka the first'
                      ' bot-admin'),

    'files': _('list bot file paths'),

    'verifyme': _('verify that the user has a 1-to-1 conversation with the bot.'
                  '\noptionally, supply a user chat id to test a user other '
                  'than yourself.'),

    'test_one2one_message': _('send a test message instructing the user to open'
                              'a 1-to-1 hangout with the bot'),
}


def _initialise():
    plugins.register_admin_command([
        "files",
        "test_one2one_message",
    ])
    plugins.register_user_command([
        "iamspartacus",
        "verifyme",
    ])
    plugins.register_help(HELP)


def iamspartacus(bot, event, *dummys):
    """announce to the bot that you are spartacus"""
    admin_key = "admins"
    global_admins = bot.config.get_option(admin_key)
    if not global_admins:
        chat_id = event.user_id.chat_id
        initial_admin_list = [chat_id]
        bot.config[admin_key] = initial_admin_list
        bot.config.save()
        return _('<i>Starter: Configuring first admin: {}</i>').format(chat_id)
    return _("<i>No! I am Spartacus!</i>")


async def files(bot, event, *dummys):
    """list bot file paths"""
    if not await bot.coro_send_to_user(
            event.user_id.chat_id, _('<i>config: {}\nmemory: {}</i>').format(
                bot.config.filename, bot.memory.filename)):
        await _one2one_required(bot, event.conv)


async def verifyme(bot, event, *args):
    """verify that the user has a 1-to-1 conversation with the bot."""

    if not args:
        chat_id = event.user.id_.chat_id
    else:
        chat_id = " ".join(args)

    one2one = await bot.get_1to1(chat_id, force=True)
    if one2one:
        if event.user_id.chat_id == chat_id:
            # send a private message only if the actual user requested it
            await bot.coro_send_message(
                one2one,
                _(
                    '<i>verification completed - this is your one-to-one chat '
                    'with the bot</i>'))

        if event.conv_id != one2one.id_:
            # announce verification wherever it was requested
            await bot.coro_send_message(
                event.conv,
                _(
                    '<i>verified - user has a one-to-one conversation with '
                    'me</i>'))
    else:
        # provide standard instructions if no one-2-one exists
        await _one2one_required(bot, event.conv)


async def test_one2one_message(bot, event, *dummys):
    """send a test message instructing the user to open a 1on1 with the bot"""
    await _one2one_required(bot, event.conv_id)


async def _one2one_required(bot, target_conversation):
    myself = bot.user_self()
    url = 'https://hangouts.google.com/chat/person/%s' % myself['chat_id']
    await bot.coro_send_message(target_conversation,
                                _VERIFY_TEXT.format(url=url,
                                                    bot_cmd=bot.command_prefix))
