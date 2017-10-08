import logging

import hangups


logger = logging.getLogger(__name__)


async def geticon(bot, event, *args):
    """ Return the avatar of the person who called this command """

    _response = await bot.get_entity_by_id(
        hangups.hangouts_pb2.GetEntityByIdRequest(
            request_header=bot.get_request_header(),
            batch_lookup_spec=[
                hangups.hangouts_pb2.EntityLookupSpec(
                    gaia_id=event.user_id.chat_id)]))

    try:
        photo_uri = _response.entity[0].properties.photo_url
    except Exception as err:
        logger.exception("%s %s %s", event.user_id.chat_id, err, _response)

    await bot.coro_send_message(event.conv_id, photo_uri)
