#!/usr/bin/python3

import datetime
import random
import tempfile

from typing import BinaryIO, Optional

import discord

import utils

# Returns a format string with lines of the form:
#   [1-indexed row number] [entry] [marker]
#
# Where marker is a text "arrow" pointing to the specified index.
def _format_listing(entries: list[str], index: int) -> str:
  nums = [str(i + 1) + '.' for i in range(len(entries))]
  markers = ['[<]' if i == index else '' for i in range(len(entries))]

  return utils.format_table(zip(*[nums, entries, markers]))


# Wrapper around FFmpegOpusAudio that counts the number of milliseconds streamed so far.
class ResumedAudio(discord.FFmpegOpusAudio):
  _TARGET_BITRATE: int = 96
  _READ_AUDIO_CHUNK_TIME: datetime.timedelta = datetime.timedelta(
      milliseconds=20)

  def __init__(self, filename: str, elapsed: datetime.timedelta):
    # For error reporting.
    self._filename: str = utils.file_stem(filename)

    self._stderr: BinaryIO = tempfile.TemporaryFile('a+b')

    # Final error status. Used once _stderr has been cleaned up.
    self._final_error: Optional[bool] = None

    # TODO: foward args if more sophisticated construction is needed.
    super().__init__(filename, bitrate=self._TARGET_BITRATE, stderr=self._stderr,
                     options=f'-bufsize {2*self._TARGET_BITRATE}k',
                     before_options=f'-ss {str(elapsed)}')

    self._elapsed: datetime.timedelta = elapsed

  def read(self) -> bytes:
    self._elapsed += self._READ_AUDIO_CHUNK_TIME
    return super().read()

  def cleanup(self) -> None:
    # Clean up process first to make sure stderr is populated.
    super().cleanup()

    # Save error state so that we can still query error even though our resources have been cleaned
    # up.
    self._final_error = self.HasError()
    self._stderr.close()

  # Returns True if ffmpeg stderr contains a known playback error.
  def HasError(self) -> bool:
    if self._final_error is not None:
      return self._final_error

    try:
      self._stderr.seek(0)
      err_string: str = self._stderr.read().decode('utf8')

      if 'Invalid data' in err_string:
        utils.log(utils.LogSeverity.ERROR, f'Error reading "{self._filename}".')
        return True

      return False
    except BaseException:
      return True

  @property
  def elapsed(self) -> datetime.timedelta:
    return self._elapsed


# Maintains a cursor in a list of music files and exposes an audio stream for the current file.
class Playlist:

  def __init__(self, name: str, fs: list[str]):
    # Make copy.
    self._name: str = name
    self._fs: list[str] = list(fs)

    # Start shuffled.
    self.Restart()

  # Clear current song and reshuffle playlist.
  def Restart(self) -> None:
    utils.log(utils.LogSeverity.INFO, f'Restarting playlist "{self._name}".')

    self._index: int = 0
    self._cur_src: Optional[ResumedAudio] = None
    self._ff: datetime.timedelta = datetime.timedelta()
    random.shuffle(self._fs)

  # Returns a new stream that plays the track from the position last left off by any previous
  # stream, plus any subsequent fast-forwarding.
  #
  # Caller is responsible for cleaning up resources for the returned stream.
  async def MakeStream(self) -> Optional[ResumedAudio]:
    if self._index >= len(self._fs):
      return None

    if self._cur_src:
      utils.log(utils.LogSeverity.INFO,
                f'Resuming "{self.current_track_name}".')
      self._cur_src = ResumedAudio(
          self._fs[self._index], self._cur_src.elapsed + self._ff)
    else:
      utils.log(utils.LogSeverity.INFO,
                f'Starting "{self.current_track_name}".')
      self._cur_src = ResumedAudio(self._fs[self._index], self._ff)

    # When resuming the audio, the current fast-forward amount is already inherited from the
    # previous stream.
    self._ff = datetime.timedelta()

    return self._cur_src

  # Skips forward into the track for subsequent calls to MakeStream. Existing stream objects are
  # unaffected.
  def FastForward(self, duration: datetime.timedelta) -> None:
    if self._index >= len(self._fs):
      return

    self._ff += duration

  def StreamHasError(self) -> bool:
    return self._index >= len(self._fs) or self._cur_src is not None and self._cur_src.HasError()

  # Move to the next song, reshuffling and starting again if there isn't one.
  def Skip(self) -> None:
    self._index += 1

    if self._index >= len(self._fs):
      self.Restart()
      return

    self._cur_src = None
    self._ff = datetime.timedelta()

  # Returns a full track listing with a cursor next to the currently-playing track.
  def GetTrackListing(self) -> str:
    titles: list[str] = [utils.file_stem(fn) for fn in self._fs]
    return f'{self._name}:\n\n' + _format_listing(titles, self._index)

  @property
  def name(self) -> str:
    return self._name

  @property
  def current_track_name(self) -> Optional[str]:
    return None if not self._fs else utils.file_stem(self._fs[self._index])


# Resturns a playlist listing. Puts a cursor next to one "index" playlist.
def get_playlist_listing(playlists, index):
  return 'Playlists:\n\n' + _format_listing(playlists, index)
