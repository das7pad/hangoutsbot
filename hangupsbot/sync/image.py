"""wrapper for image info"""
__author__ = 'das7pad@outlook.com'

import asyncio
import io
import logging
import os
import time
import warnings

import aiohttp

from PIL import Image
import imageio
# Note: moviepy depends on imageio and ffmpeg
# the download will happen only once, as it will be cached to a path similar to
#  ~/.imageio/ffmpeg/ffmpeg.linux64
#   this path can not be changed, install ffmpeg to avoid a download
#pylint: disable=wrong-import-position
imageio.plugins.ffmpeg.download()
from moviepy.editor import VideoFileClip

from hangupsbot.base_models import BotMixin

from .exceptions import MissingArgument

VALID_IMAGE_TYPES = ('photo', 'sticker', 'gif', 'video')

FORMAT_MAPPING = {
    'jpg': 'JPEG',
    'jpeg': 'JPEG',
    'png': 'PNG',
    'gif': 'GIF',
    'gifv': 'GIF',
    'mp4': 'MP4',
    'avi': 'AVI'
}

TYPE_MAPPING = {
    'jpg': 'photo',
    'jpeg': 'photo',
    'png': 'photo',
    'webm': 'sticker',
    'webp': 'sticker',
    'gif': 'gif',
    'gifv': 'gif',
    'mp4': 'video',
    'avi': 'video'
}

DEFAULT_SIZE = (0, 0)
MOVIE_EXTENSIONS = ('mp4', 'avi', 'gif')

PATH = '/tmp/image_sync_RAW'

logger = logging.getLogger(__name__)

class MovieConverter(VideoFileClip):
    """Converter that saves one dump to file on gif convert of a video

    Args:
        raw (io.BytesIO): the raw video data
        file_format (str): file extension of the video
    """
    def __init__(self, raw, file_format):
        self._path = '{}-{}.{}'.format(PATH, time.time(), file_format)
        raw.seek(0)
        with open(self._path, 'wb') as writer:
            writer.write(raw.read())

        super().__init__(self._path)

    def to_video(self):
        """save the video to a file-like object

        Returns:
            io.BytesIO: the video
        """
        logger.debug('to_video')
        path = self._path + '.mp4'
        self.write_videofile(path, verbose=False, progress_bar=False)
        data = io.BytesIO(open(path, 'rb').read())
        self.cleanup(path)
        return data

    def to_gif(self, fps=10):
        """return the video as gif

        like moviepy.video.io.gif_writers.write_gif_with_image_io but handling
         the image data in memory

        Args:
            fps (int): frames per second for the breakdown

        Returns:
            io.BytesIO: the new image
        """
        logger.debug('to_gif')
        data = io.BytesIO()
        with imageio.save(data, format='gif', duration=1/fps,
                          quantizer=0, palettesize=256) as writer:
            for frame in self.iter_frames(fps=fps, dtype='uint8'):
                writer.append_data(frame)
            writer.close()
        return data

    def cleanup(self, path=None):
        """delete a created file

        Args:
            path (str): defaults to the source file path
        """
        if path is None:
            path = self._path
        try:
            if os.path.exists(path):
                os.remove(path)
        except (OSError, IOError):
            logger.warning('failed to remove %s', self._path)

    def __del__(self):
        super().__del__()
        self.cleanup()


class SyncImage(BotMixin):
    """store info to a synced image in one object and convert movies to gif

    provide either a public url or image data and a filename

    Args:
        data (io.BytesIO): containing the raw image_data
        cache (int): time in sec for the upload info to remain in cache
        filename (str): including a valid image file extension
        type_ (str): 'photo', 'sticker', 'gif', 'video'
        size (tuple): a tuple of int, width and height in px
        url (str): public url of the image
        cookies (dict): custom cookies to authenticate a download
        headers (dict): custom header to authenticate a download

    Raises:
        MissingArgument: no url/data were given
    """
    # pylint: disable=too-many-instance-attributes

    # an incomplete init should not break __del__
    _data = None
    _movie = None
    _size_cache = {}

    def __init__(self, *, data=None, cache=None, filename=None, type_=None,
                 size=None, url=None, cookies=None, headers=None):

        self._type = type_
        self.cache = cache
        self._size_cache = {}
        self._data = data
        self._download_auth = {'cookies': cookies, 'headers': headers}
        self._filename = None
        self._size = (size if isinstance(size, tuple) and len(size) == 2
                      else (size, size) if isinstance(size, (int, float))
                      else DEFAULT_SIZE)
        self._movie = None

        self.update_from_filename(
            filename if isinstance(filename, str) and filename else
            url if isinstance(url, str) and url else None)

        self._url = url if isinstance(url, str) and url else None

        if self._url is None and self._data is None:
            raise MissingArgument('no image url or data provided')

    ############################################################################
    # PUBLIC METHODS
    ############################################################################

    @property
    def type_(self):
        """complete an undefined type with the default 'photo'

        Returns:
            str:  'photo', 'sticker', 'gif' or 'video'
        """
        return self._type or 'photo'

    def update_from_filename(self, filename):
        """update the filename and image type from a given filename

        Args:
            filename (str): a filename or url containing the file extension
        """
        if isinstance(filename, str):
            extension = filename.lower().rsplit('.', 1)[-1]
            self._type = self._type or TYPE_MAPPING.get(extension)
        else:
            filename = self._filename or (str(time.time()) + '.jpg')

        if self._type not in VALID_IMAGE_TYPES:
            filename += '.jpg'
            self.cache = 1

        self.cache = (self.cache if isinstance(self.cache, int) else
                      self.bot.config['sync_cache_timeout_%s' % self.type_])

        self._filename = filename.rsplit('/', 1)[-1].lower()

    def get_data(self, limit=None, video_as_gif=False):
        """get the resized image and its filename

        cache requests per image to safe CPU- and IO-time of resizing

        Args:
            limit (int): a custom image size in px
            video_as_gif (bool): toggle to convert videos to gifs

        Returns:
            tuple: io.BytesIO instance, the image data and string, the filename;
            if no data is available return None, <string with reason>
        """
        if self._data is None:
            return None, '[Image has no content]'

        extension = self._filename.lower().rsplit('.', 1)[-1]

        # also convert images that should not be movies to gif
        video_as_gif = (self._movie is not None
                        and extension in MOVIE_EXTENSIONS
                        and (video_as_gif or self._type != 'video'))

        cache_key = (limit, video_as_gif)
        if cache_key in self._size_cache:
            data, filename = self._size_cache[cache_key]
            return io.BytesIO(data.getvalue()), filename

        filename = self._filename

        if extension in MOVIE_EXTENSIONS and self._meets_size_limit:
            filename_raw = filename.rsplit('.', 1)[0]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if video_as_gif:
                    if not self._meets_size_limit:
                        image_data_size = len(self._data.getvalue())
                        return None, ('[%s is too big to convert to GIF: %dKB]'
                                      % (self._type, image_data_size/1024))
                    data = self._movie.to_gif()
                    filename = filename_raw + '.gif'
                else:
                    filename = filename_raw + '.mp4'
                    data = (self._data if self._filename.endswith('.mp4')
                            else self._movie.to_video())

        else:
            data = self._data

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            limit = limit if isinstance(limit, int) else 0
            data, filename = self._get_resized(limit=limit, data=data,
                                               filename=filename,
                                               video_as_gif=video_as_gif)
        self._size_cache[cache_key] = (data, filename)
        return io.BytesIO(data.getvalue()), filename

    async def process(self):
        """fetch image data if not already done"""
        if not await self._download():
            return

        extension = self._filename.lower().rsplit('.', 1)[-1]

        if (self._movie is None and extension in MOVIE_EXTENSIONS
                and self._meets_size_limit):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._movie = await asyncio.get_event_loop().run_in_executor(
                    None, MovieConverter, self._data, extension)
                self._size = self._movie.size

    ############################################################################
    # PRIVATE METHODS
    ############################################################################

    async def _download(self):
        """download the image data if not already done cached

        Returns:
            bool: False if no data is available, otherwise True
        """
        if self._data is not None:
            self._data.seek(0)  # reset pointer
            return True

        url = self._url
        try:
            async with aiohttp.ClientSession(**self._download_auth) as session:
                # validate the file extension first
                async with session.get(url, allow_redirects=True) as resp:
                    resp.raise_for_status()
                    headers = resp.headers

                    if ('image' not in headers['content-type'] and
                            'video' not in headers['content-type']):
                        raise TypeError(
                            '%s has no image\nheaders=%s' % (url, headers))

                    if 'content-disposition' in headers:
                        # example for a content-disposition:
                        # inline;filename="2332232027763463203?account_id=1.png"
                        for part in headers['content-disposition'].split(';'):
                            if part.startswith('filename="'):
                                filename = part[10:-1].strip()
                                self.update_from_filename(filename)
                                break

                    extension = headers['content-type'].split('/', 1)[1]
                    if not self._filename.endswith(extension):
                        self.update_from_filename('%s.%s' % (time.time(),
                                                             extension))
                    self._data = io.BytesIO(await resp.read())

            return True
        except (aiohttp.ClientError, AttributeError, TypeError) as err:
            logger.error('can not fetch image data from %s: %s', url, repr(err))
            return False

    def _get_resized(self, *, limit, data, filename, video_as_gif, caller=None):
        """resize the image, the size applies to both width and height

        Args:
            limit (int): in px the new size
            data (io.BytesIO): initial instance
            filename (str): filename with extension
            video_as_gif (bool): toggle to get a video wrapped in a gif
            caller (mixed): set to a non value to block a loop

        Returns:
            tuple: a new io.BytesIO instance with the raw resized image data
            and the new filename
        """
        def _remove_background(data, filename):
            """remove background in saving as PNG

            Args:
                data (io.BytesIO): image data to override
                filename (str): image file name to override

            Returns:
                tuple: a io.BytesIO instance, the image as PNG
                       and a str, the new filename
            """
            if filename.rsplit('.', 1)[-1].lower() == 'png':
                # already a png, no need to format again
                return data, filename

            if self._movie is not None:
                # animated image, invalid request
                return data, filename

            if not self._meets_size_limit:
                # to big to resize
                return

            try:
                container = io.BytesIO(data.getbuffer())
                image = Image.open(container)
                self._size = image.width, image.height
                new_data = io.BytesIO()
                image.save(new_data, 'PNG', compression_level=7)
                image.close()
                container.close()
            except (IOError, KeyError):
                logger.exception('failed to save as png')
            else:
                data = new_data

                # update the filename to .png
                filename = filename.rsplit('.', 1)[0] + '.png'
                logger.debug('converted %s to PNG', self._filename)
            data.seek(0)
            return data, filename

        def _resize():
            """calculate the new size and resize the image

            Returns:
                io.BytesIO: instance with the image data, it may not be resized
                    if it already matches the required size or an error occutred
            """
            message = 'open %s'
            logger.debug(message, filename)
            try:
                if self._movie is not None:
                    image = self._movie
                    resize_arg = None

                else:
                    image = Image.open(io.BytesIO(data.getvalue()))
                    self._size = image.size
                    resize_arg = Image.HAMMING

                message = 'calculate a new size for %s'
                logger.debug(message, filename)
                new_size = self._size
                if new_size[1] > limit:
                    new_size = (int(new_size[0]/(new_size[1]/limit)), limit)

                if new_size[0] > limit:
                    new_size = (limit, int(new_size[1]/(new_size[0]/limit)))

                if new_size == self._size:
                    # there is no need to change the size
                    data.seek(0)
                    return data

                message = 'resize %s'
                logger.debug(message, filename)
                new_image = image.resize(new_size, resize_arg)

                message = 'export %s'
                logger.debug(message, filename)
                if self._movie is not None:
                    if video_as_gif:
                        new_image_data = new_image.to_gif()
                    else:
                        new_image_data = new_image.to_video()
                    new_image.cleanup()

                else:
                    new_image_data = io.BytesIO()
                    new_image.save(new_image_data,
                                   FORMAT_MAPPING[filename.rsplit('.', 1)[-1]])

            except (OSError, IOError, KeyError, AttributeError):
                logger.exception('failed to ' + message, filename)
                return data

            return new_image_data

        extension = filename.rsplit('.', 1)[-1]
        if extension in MOVIE_EXTENSIONS and self._movie is None:
            # MovieConverter missing
            return data, filename

        formatting = FORMAT_MAPPING.get(extension)
        if formatting is None and caller is None:
            # convert to PNG
            data, filename = _remove_background(data, filename)
            return self._get_resized(limit=limit, data=data, filename=filename,
                                     video_as_gif=video_as_gif, caller='self')

        if (limit < 1 or self._size != DEFAULT_SIZE
                and (self._size[0] < limit and self._size[1] < limit)):
            # no valid new size limit or the image already meets the criteria
            return data, filename

        return _resize(), filename

    @property
    def _meets_size_limit(self):
        """check the image size against the hard limit for media processing

        Returns:
            bool: True if size is below the limit, otherwise False
        """
        below = (len(self._data.getvalue())
                 < (self.bot.config['sync_process_animated_max_size']*1024))
        if not below:
            logger.info("%s does not meet the video-to-gif process size limit",
                        str(self))
        return below

    def __str__(self):
        return ' | '.join(('SyncImage',
                           'type:%s' % self._type,
                           'name:%s' % self._filename,
                           'size:%sKB' % ((len(self._data.getvalue()) / 1024)
                                          if self._data is not None
                                          else 'empty'),
                           'movie:%s' % self._movie))

    def __del__(self):
        """explicit cleanup"""
        if self._movie is not None:
            self._movie = None
        for data, dummy in self._size_cache.values():
            data.close()
        self._size_cache.clear()
        if self._data is not None:
            self._data.close()
