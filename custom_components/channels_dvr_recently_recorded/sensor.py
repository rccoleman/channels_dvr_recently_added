"""
Home Assistant component to feed the Upcoming Media Lovelace card with
Channels DVR recently recorded shows.

https://github.com/custom-cards/upcoming-media-card

"""
from custom_components.channels_dvr_recently_recorded.api import ConnectionFail
from custom_components.channels_dvr_recently_recorded import DOMAIN
import logging
from homeassistant.core import callback
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.device_registry import DeviceEntryType
from dateutil.parser import parse
from urllib.parse import urlparse
from datetime import timedelta


SCAN_INTERVAL = timedelta(seconds=30)
_LOGGER = logging.getLogger(__name__)

CONF_DL_IMAGES = "dl_images"
CONF_HOSTNAME = "hostname"
CONF_IMG_DIR = "img_dir"
CONF_MAX = "max"
CONF_VERIFICATION = "verification"

AIRDATE = "airdate"
AIRED = "aired"
FLAG = "flag"
RUNTIME = "runtime"
NUMBER = "number"
GENRES = "genres"
RATING = "rating"
POSTER = "poster"
FANART = "fanart"
TITLE = "title"
EPISODE = "episode"
RELEASE = "release"
TITLE_DEFAULT = "title_default"
LINE1_DEFAULT = "line1_default"
LINE2_DEFAULT = "line2_default"
LINE3_DEFAULT = "line3_default"
LINE4_DEFAULT = "line4_default"
ICON = "icon"

DEFAULT_NAME = "Recently Recorded"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up sensor entity."""
    async_add_entities([ChannelsDVRRecentlyRecordedSensor(hass, config_entry)])


class ChannelsDVRRecentlyRecordedSensor(Entity):
    def __init__(self, hass, conf):
        self._name = conf.data.get(CONF_NAME)
        self.conf_dir = str(hass.config.path()) + "/"
        self._dir = conf.data.get(CONF_IMG_DIR)
        if self._name:
            self._dir = self._dir + self._name.replace(" ", "_") + "/"
        self.max_items = int(conf.data.get(CONF_MAX))
        self.dl_images = conf.data.get(CONF_DL_IMAGES)
        self.verification = conf.data.get(CONF_VERIFICATION)
        self._state = None
        self._attrs = []
        self._channels_dvr = hass.data[DOMAIN][conf.entry_id]
        self.version = self._channels_dvr.version
        _LOGGER.debug(f"{self.version}")

    @property
    def name(self):
        """Return the name of the entity"""
        return self._name

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    @property
    def state_attributes(self):
        """Return the attribute dict."""
        if not len(self._attrs):
            return
        return {"data": self._attrs}

    @property
    def unique_id(self):
        """Return unique ID."""
        return self.verification

    @property
    def device_info(self):
        """Device info."""
        _LOGGER.debug(f"Version: {self.version}")
        return {
            "identifiers": {(DOMAIN, self.verification)},
            "name": "Channels DVR Recordings",
            "manufacturer": "Channels",
            "model": "DVR Server",
            "default_name": "Channels DVR Recordings",
            "entry_type": DeviceEntryType.SERVICE,
            "sw_version": self.version,
        }

    @callback
    async def async_added_to_hass(self):
        """Called when the entity is added to HA.  Won't be called if the entity is disabled."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self):
        """Called to update the entity state & attributes."""
        import os
        import re

        try:
            files = await self._channels_dvr.get_files()
        except ConnectionFail as err:
            self._state = err.msg
            return

        self._state = "Online"

        """Only look for recorded programs"""
        recordings = [x for x in files if x.get("JobID", "") != "" and x.get("Deleted", False) == False]
        recordings.sort(
            reverse=True, key=lambda x: parse(x["Airing"]["Raw"]["startTime"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        if self.dl_images:
            directory = self.conf_dir + "www" + self._dir
            if not os.path.exists(directory):
                os.makedirs(directory, mode=0o777)

            """Make list of images in dir that use our naming scheme"""
            dir_re = re.compile(r"p.+\.jpg")
            dir_images = list(filter(dir_re.search, os.listdir(directory)))
            remove_images = dir_images.copy()

        self._attrs = []

        attr = {
            TITLE_DEFAULT: "$title",
            LINE1_DEFAULT: "$episode",
            LINE2_DEFAULT: "$release",
            LINE3_DEFAULT: "$number - $rating - $runtime",
            LINE4_DEFAULT: "$genres",
            ICON: "mdi:eye",
        }

        self._attrs.append(attr)

        num_items = 0

        for recording in recordings:
            episode = recording["Airing"]

            num_items += 1
            if num_items > self.max_items:
                break

            attr = {
                AIRDATE: ""
                if not episode["Raw"].get("startTime", None)
                else parse(episode["Raw"]["startTime"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
                AIRED: episode.get("OriginalDate", ""),
                FLAG: recording.get("Watched", False),
                TITLE: episode.get("Title", ""),
                EPISODE: episode.get("EpisodeTitle", ""),
                RELEASE: "$day, $date $time",
                NUMBER: "S%02d" % episode.get("SeasonNumber", 0)
                + "E%02d" % episode.get("EpisodeNumber", 0),
                RUNTIME: episode["Raw"].get("duration", 0),
                GENRES: episode.get("Genres", ""),
                RATING: ""
                if not hasattr(episode["Raw"], "ratings")
                else episode["Raw"]["ratings"][0]["code"],
                POSTER: episode["Raw"]["program"]["preferredImage"].get("uri", ""),
            }

            image_uri = episode["Raw"]["program"]["preferredImage"]["uri"]

            if not self.dl_images:
                attr[POSTER] = image_uri
            else:
                """Update if media items have changed or images are missing"""
                filename = urlparse(image_uri).path.rsplit("/", 1)[-1]
                if filename not in dir_images:
                    try:
                        poster_image = await self._channels_dvr.get_poster(image_uri)
                    except ConnectionFail as err:
                        poster_image = None

                    if poster_image is not None:
                        image_file = directory + filename
                        open(image_file, "wb").write(poster_image)
                elif filename in remove_images:
                    remove_images.remove(filename)
                attr[POSTER] = "/local" + self._dir + filename

            self._attrs.append(attr)

        if self.dl_images:
            """Remove items no longer in the list"""
            _LOGGER.debug(f"Removing {remove_images}")
            [os.remove(directory + x) for x in remove_images]

        _LOGGER.debug(f"Finished updating")
