#!/usr/bin/python3

import datetime
import random
import tempfile

from typing import BinaryIO, Optional

import discord

import utils


def _format_listing(entries: list[str], index: int) -> str:
  """Return a format string with lines of the form:

    [1-indexed row number] [entry] [marker]

  Where marker is a text "arrow" pointing to the specified index.
  """

  nums = [str(i + 1) + "." for i in range(len(entries))]
  markers = ["[<]" if i == index else "" for i in range(len(entries))]

  return utils.format_table(zip(*[nums, entries, markers]))


class ResumedAudio(discord.FFmpegOpusAudio):
  """Wrapper around FFmpegOpusAudio that counts the number of milliseconds streamed so far."""

  _TARGET_BITRATE: int = 96
  _READ_AUDIO_CHUNK_TIME: datetime.timedelta = datetime.timedelta(milliseconds=20)

  def __init__(self, filename: str, elapsed: datetime.timedelta):
    # For error reporting.
    self._filename: str = utils.file_stem(filename)

    self._resumed_stderr: BinaryIO = tempfile.TemporaryFile("a+b")

    # Final error status. Used once _stderr has been cleaned up.
    self._final_error: Optional[bool] = None

    # TODO: foward args if more sophisticated construction is needed.
    super().__init__(
      filename,
      bitrate=self._TARGET_BITRATE,
      stderr=self._resumed_stderr,
      options=f'-filter:a "dynaudnorm=p=0.9:s=5" -bufsize {2 * self._TARGET_BITRATE}k',
      before_options=f"-ss {str(elapsed)}",
    )

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
    self._resumed_stderr.close()

  def HasError(self) -> bool:
    """Return true if ffmpeg stderr contains a known playback error."""

    if self._final_error is not None:
      return self._final_error

    try:
      self._resumed_stderr.seek(0)
      err_string: str = self._resumed_stderr.read().decode("utf8")

      if "Invalid data" in err_string:
        utils.log(utils.LogSeverity.ERROR, f'Error reading "{self._filename}".')
        return True

      return False
    except BaseException:
      return True

  @property
  def elapsed(self) -> datetime.timedelta:
    return self._elapsed


class Playlist:
  """Maintain a cursor in a list of music files and expose an audio stream for the current file."""

  def __init__(self, name: str, fs: list[str]):
    # Make copy.
    self._name: str = name
    self._fs: list[str] = list(fs)

    # Start shuffled.
    self.Restart()

  def Restart(self) -> None:
    """Clear current song and reshuffle playlist."""

    utils.log(utils.LogSeverity.INFO, f'Restarting playlist "{self._name}".')

    self._index: int = 0
    self._cur_src: Optional[ResumedAudio] = None
    self._ff: datetime.timedelta = datetime.timedelta()
    random.shuffle(self._fs)

  async def MakeStream(self) -> Optional[ResumedAudio]:
    """Return a new stream that plays the track from the position last left off by any previous
    stream, plus any subsequent fast-forwarding.

    Caller is responsible for cleaning up resources for the returned stream.
    """

    if self._index >= len(self._fs):
      return None

    if self._cur_src:
      utils.log(utils.LogSeverity.INFO, f'Resuming "{self.current_track_name}".')
      self._cur_src = ResumedAudio(self._fs[self._index], self._cur_src.elapsed + self._ff)
    else:
      utils.log(utils.LogSeverity.INFO, f'Starting "{self.current_track_name}".')
      self._cur_src = ResumedAudio(self._fs[self._index], self._ff)

    # When resuming the audio, the current fast-forward amount is already inherited from the
    # previous stream.
    self._ff = datetime.timedelta()

    return self._cur_src

  def FastForward(self, duration: datetime.timedelta) -> None:
    """Skip forward into the track for subsequent calls to MakeStream.
    
    Existing stream objects are unaffected."""

    if self._index >= len(self._fs):
      return

    self._ff += duration

  def StreamHasError(self) -> bool:
    return self._index >= len(self._fs) or self._cur_src is not None and self._cur_src.HasError()

  def Skip(self) -> None:
    """Move to the next song, reshuffling and starting again if there isn't one."""

    self._index += 1

    if self._index >= len(self._fs):
      self.Restart()
      return

    self._cur_src = None
    self._ff = datetime.timedelta()

  def GetTrackListing(self) -> str:
    """Return a full track listing with a cursor next to the currently-playing track."""

    titles: list[str] = [utils.file_stem(fn) for fn in self._fs]
    return f"{self._name}:\n\n" + _format_listing(titles, self._index)

  @property
  def name(self) -> str:
    return self._name

  @property
  def current_track_name(self) -> Optional[str]:
    return None if not self._fs else utils.file_stem(self._fs[self._index])


def get_playlist_listing(playlists: list[str], index: int):
  """Return a playlist listing. Put a cursor next to one "index" playlist."""

  return "Playlists:\n\n" + _format_listing(playlists, index)
