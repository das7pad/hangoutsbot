import random
import asyncio

import hangups

from commands import Help
import plugins

EGGS = (
    'ponies',
    'pitchforks',
    'bikeshed',
    'shydino',
)

HELP = {
    'easteregg': _('starts hangouts easter egg combos.\n'
                   'supply up to three parameters:\n'
                   '  - easter egg trigger name\n'
                   '     ponies, pitchforks, bikeshed or shydino\n'
                   '  - number of times\n'
                   '  - period between eastereggs (in seconds)\n'),
}

def _initialise():
    plugins.register_admin_command(["easteregg"])
    plugins.register_help(HELP)


async def easteregg(bot, event, *args):
    """start hangouts easter egg combos."""
    if not args:
        raise Help()

    easteregg_name = args[0]
    eggcount = int(args[1]) if len(args) > 1 and not args[1].isdigit() else 1
    period = float(args[2]) if len(args) > 2 and not args[2].isdigit() else 0.5

    for dummy in range(eggcount):
        # pylint:disable=protected-access
        await bot._client.easter_egg(
            hangups.hangouts_pb2.EasterEggRequest(
                request_header=bot._client.get_request_header(),
                conversation_id=hangups.hangouts_pb2.ConversationId(
                    id=event.conv_id),
                easter_egg=hangups.hangouts_pb2.EasterEgg(
                    message=easteregg_name)))

        if eggcount > 1:
            await asyncio.sleep(period + random.uniform(-0.1, 0.1))
