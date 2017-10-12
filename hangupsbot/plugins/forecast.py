# coding: utf-8
"""
Use DarkSky.net to get current weather forecast for a given location.

Instructions:
    * Get an API key from https://darksky.net/dev/
    * Store API key in config.json:forecast_api_key
"""
import logging
from decimal import Decimal

import aiohttp

import plugins

logger = logging.getLogger(__name__)
_internal = {}

HELP = {
    'setweatherlocation': _('Sets the Lat Long default coordinates for this '
                            'hangout when polling for weather data\n'
                            '{bot_cmd} setWeatherLocation <location>'),

    'weather': _("Returns weather information from darksky.net\n"
                 " <b>{bot_cmd} weather <location></b>\n"
                 "   Get location's current weather.\n"
                 " <b>{bot_cmd} weather</b>\n"
                 "   Get the hangouts default location's current weather. If "
                 "the  default location is not set talk to a hangout admin."),

    'forecast': _("Returns a brief textual forecast from darksky.net\n"
                  " <b>{bot_cmd} weather <location></b>\n"
                  "   Get location's current forecast.\n"
                  " <b>{bot_cmd} weather</b>\n"
                  "   Get the hangouts default location's forecast. If default "
                  "location is not set talk to a hangout admin."),
}

def _initialize(bot):
    api_key = bot.config.get_option('forecast_api_key')
    if api_key:
        _internal['forecast_api_key'] = api_key
        plugins.register_user_command(['weather', 'forecast'])
        plugins.register_admin_command(['setweatherlocation'])
        plugins.register_help(HELP)
    else:
        logger.debug('WEATHER: config["forecast_api_key"] required')

async def setweatherlocation(bot, event, *args):
    """Sets the Lat Long default coordinates for this hangout"""
    location = ''.join(args).strip()
    if not location:
        return _('No location was specified, please specify a location.')

    location = await _lookup_address(location)
    if location is None:
        return _('Unable to find the specified location.')

    if not bot.memory.exists(["conv_data", event.conv.id_]):
        bot.memory.set_by_path(['conv_data', event.conv.id_], {})

    bot.memory.set_by_path(["conv_data", event.conv.id_, "default_weather_location"], {'lat': location['lat'], 'lng': location['lng']})
    bot.memory.save()
    return _('This hangouts default location has been set to {}.').format(location)

async def weather(bot, event, *args):
    """Returns weather information from darksky.net"""
    weather_data = await _get_weather(bot, event, args)
    if weather_data:
        return _format_current_weather(weather_data)
    return _('There was an error retrieving the weather, guess you need to look outside.')

async def forecast(bot, event, *args):
    """Returns a brief textual forecast from darksky.net"""
    weather_data = await _get_weather(bot, event, args)
    if weather_data:
        return _format_forecast_weather(weather_data)
    return _('There was an error retrieving the weather, guess you need to look outside.')

def _format_current_weather(weather_data):
    """
    Formats the current weather data for the user.
    """
    weatherStrings = []
    if 'temperature' in weather_data:
        weatherStrings.append("It is currently: <b>{0}°{1}</b>".format(round(weather_data['temperature'], 2), weather_data['units']['temperature']))
    if 'summary' in weather_data:
        weatherStrings.append("<i>{0}</i>".format(weather_data['summary']))
    if 'feelsLike' in weather_data:
        weatherStrings.append("Feels Like: {0}°{1}".format(round(weather_data['feelsLike'], 2), weather_data['units']['temperature']))
    if 'windspeed' in weather_data:
        weatherStrings.append("Wind: {0} {1} from {2}".format(round(weather_data['windspeed'], 2), weather_data['units']['windSpeed'], _get_wind_direction(weather_data['windbearing'])))
    if 'humidity' in weather_data:
        weatherStrings.append("Humidity: {0}%".format(weather_data['humidity']))
    if 'pressure' in weather_data:
        weatherStrings.append("Pressure: {0} {1}".format(round(weather_data['pressure'], 2), weather_data['units']['pressure']))

    return "\n".join(weatherStrings)

def _format_forecast_weather(weather_data):
    """
    Formats the forecast data for the user.
    """
    weatherStrings = []
    if 'hourly' in weather_data:
        weatherStrings.append("<b>Next 24 Hours</b>\n{}". format(weather_data['hourly']))
    if 'daily' in weather_data:
        weatherStrings.append("<b>Next 7 Days</b>\n{}". format(weather_data['daily']))

    return "\n".join(weatherStrings)

async def _lookup_address(location):
    """
    Retrieve the coordinates of the location from googles geocode api.
    Limit of 2,000 requests a day
    """
    google_map_url = 'https://maps.googleapis.com/maps/api/geocode/json'
    payload = {'address': location}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(google_map_url,
                                   params=payload) as response:
                response.raise_for_status()
                raw = await response.json()
        results = raw['results'][0]
        return {
            'lat': results['geometry']['location']['lat'],
            'lng': results['geometry']['location']['lng'],
            'address': results['formatted_address']
        }
    except (IndexError, KeyError):
        logger.error('unable to parse address return data: %d: %s',
                     repr(response), repr(raw))
        return None
    except aiohttp.ClientError:
        logger.error('unable to connect with maps.googleapis.com: %d - %s',
                     google_map_url, repr(response))
        return None

async def _lookup_weather(coords):
    """
    Retrieve the current forecast for the specified coordinates from darksky.net
    Limit of 1,000 requests a day
    """

    forecast_io_url = 'https://api.darksky.net/forecast/{0}/{1},{2}?units=auto'.format(_internal['forecast_api_key'], coords['lat'], coords['lng'])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(forecast_io_url) as response:
                response.raise_for_status()
                raw = await response.json()
        current = {
            'time' : raw['currently']['time'],
            'summary': raw['currently']['summary'],
            'temperature': Decimal(raw['currently']['temperature']),
            'feelsLike': Decimal(raw['currently']['apparentTemperature']),
            'units': _get_forcast_units(raw),
            'humidity': int(raw['currently']['humidity']*100),
            'windspeed' : Decimal(raw['currently']['windSpeed']),
            'windbearing' : raw['currently']['windBearing'],
            'pressure' : raw['currently']['pressure']
        }
        if current['units']['pressure'] == 'kPa':
            current['pressure'] = Decimal(current['pressure']/10)

        if 'hourly' in raw:
            current['hourly'] = raw['hourly']['summary']
        if 'daily' in raw:
            current['daily'] = raw['daily']['summary']

    except (ValueError, KeyError) as err:
        logger.error("Forecast Error: %s", err)
        current = dict()
    except aiohttp.ClientError:
        logger.error('unable to connect with api.darksky.net: %d - %s',
                     forecast_io_url, repr(response))
        return None

    return current

async def _get_weather(bot, event, params):
    """
    Checks memory for a default location set for the current hangout.
    If one is not found and parameters were specified attempts to look up a location.
    If it finds a location it then attempts to load the weather data
    """
    parameters = list(params)
    location = {}

    if not parameters:
        if bot.memory.exists(["conv_data", event.conv.id_]):
            if bot.memory.exists(["conv_data", event.conv.id_, "default_weather_location"]):
                location = bot.memory.get_by_path(["conv_data", event.conv.id_, "default_weather_location"])
    else:
        address = ''.join(parameters).strip()
        location = await _lookup_address(address)

    if location:
        return await _lookup_weather(location)

    return {}

def _get_forcast_units(result):
    """
    Checks to see what uni the results were passed back as and sets the display units accordingly
    """
    units = {
        'temperature': 'F',
        'distance': 'Miles',
        'percipIntensity': 'in./hr.',
        'precipAccumulation': 'inches',
        'windSpeed': 'mph',
        'pressure': 'millibars'
    }
    if result['flags']:
        unit = result['flags']['units']
        if unit != 'us':
            units['temperature'] = 'C'
            units['distance'] = 'KM'
            units['percipIntensity'] = 'milimeters per hour'
            units['precipAccumulation'] = 'centimeters'
            units['windSpeed'] = 'm/s'
            units['pressure'] = 'kPa'
            if unit == 'ca':
                units['windSpeed'] = 'km/h'
            if unit == 'uk2':
                units['windSpeed'] = 'mph'
                units['distance'] = 'Miles'
    return units

def _get_wind_direction(degrees):
    """
    Determines the direction the wind is blowing from based off the degree passed from the API
    0 degrees is true north
    """
    directionText = "N"
    if degrees >= 5 and degrees < 40:
        directionText = "NNE"
    elif degrees >= 40 and degrees < 50:
        directionText = "NE"
    elif degrees >= 50 and degrees < 85:
        directionText = "ENE"
    elif degrees >= 85 and degrees < 95:
        directionText = "E"
    elif degrees >= 95 and degrees < 130:
        directionText = "ESE"
    elif degrees >= 130 and degrees < 140:
        directionText = "SE"
    elif degrees >= 140 and degrees < 175:
        directionText = "SSE"
    elif degrees >= 175 and degrees < 185:
        directionText = "S"
    elif degrees >= 185 and degrees < 220:
        directionText = "SSW"
    elif degrees >= 220 and degrees < 230:
        directionText = "SW"
    elif degrees >= 230 and degrees < 265:
        directionText = "WSW"
    elif degrees >= 265 and degrees < 275:
        directionText = "W"
    elif degrees >= 275 and degrees < 310:
        directionText = "WNW"
    elif degrees >= 310 and degrees < 320:
        directionText = "NW"
    elif degrees >= 320 and degrees < 355:
        directionText = "NNW"

    return directionText
