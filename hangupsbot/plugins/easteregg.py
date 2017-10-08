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

def _initialise():
    plugins.register_admin_command(["easteregg"])


async def easteregg(bot, event, *args):
    """starts hangouts easter egg combos.
    supply three parameters: easter egg trigger name, number of times, period (in seconds).
    supported easter egg trigger name: ponies , pitchforks , bikeshed , shydino
    """
    if not args:
        raise Help()

    easteregg_name = args[0]
    eggcount = int(args[1]) if len(args) > 1 and not args[1].isdigit() else 1
    period = float(args[2]) if len(args) > 2 and not args[2].isdigit() else 0.5

    for dummy in range(eggcount):
        await bot._client.easter_egg(
            hangups.hangouts_pb2.EasterEggRequest(
                request_header=bot._client.get_request_header(),
                conversation_id=hangups.hangouts_pb2.ConversationId(
                    id=event.conv_id),
                easter_egg=hangups.hangouts_pb2.EasterEgg(
                    message=easteregg_name)))

        if eggcount > 1:
            await asyncio.sleep(period + random.uniform(-0.1, 0.1))
