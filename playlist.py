#!/usr/bin/python3

import datetime
import sys
import random
import tempfile

import discord

import util

TARGET_BITRATE = 96
READ_AUDIO_CHUNK_TIME = datetime.timedelta(milliseconds=20)


# Returns a format string with lines of the form:
# [1-indexed row number] [entry] [marker]
#
# Where marker is a text "arrow" pointing to the specified index.
def _format_listing(entries, index):
    nums = [str(i + 1) + '.' for i in range(len(entries))]
    markers = ['[<]' if i == index else '' for i in range(len(entries))]

    return util.format_table(zip(*[nums, entries, markers]))


# Wrapper around FFmpegOpusAudio that counts the number of milliseconds
# streamed so far.
class ResumedAudio(discord.FFmpegOpusAudio):

    def __init__(self, filename, elapsed):
        # For error reporting.
        self._filename = util.file_stem(filename)
        # To capture ffmpeg error output.
        self._stderr = tempfile.TemporaryFile('a+b')
        # Final error status. Used once _stderr has been cleaned up.
        self._final_error = None

        # TODO: foward args if more sophisticated construction is needed.
        super().__init__(filename,
                         bitrate=TARGET_BITRATE,
                         stderr=self._stderr,
                         options=f'-bufsize {2*TARGET_BITRATE}k',
                         before_options=f'-ss {str(elapsed)}')

        self._elapsed = elapsed

    def read(self):
        self._elapsed += READ_AUDIO_CHUNK_TIME
        return super().read()

    def cleanup(self):
        # Clean up process first to make sure stderr is populated.
        super().cleanup()

        # Save error state so that we can still query error even though our
        # resources have been cleaned up.
        self._final_error = self.HasError()
        self._stderr.close()

    # Returns True if ffmpeg stderr contains a known playback error.
    def HasError(self):
        if self._final_error is not None:
            return self._final_error

        try:
            self._stderr.seek(0)
            err_string = self._stderr.read().decode('utf8')

            if 'Invalid data' in err_string:
                util.log(util.LogSeverity.ERROR,
                         f'Error reading "{self._filename}".')
                return True

            return False
        except:
            return True

    @property
    def elapsed(self):
        return self._elapsed


# Maintains a cursor in a list of music files and exposes an audio stream for
# the current file.
class Playlist:

    def __init__(self, name, fs):
        # Make copy.
        self._name = name
        self._fs = list(fs)

        # Populated in Restart.
        self._index = None
        self._cur_src = None
        self._ff = None

        # Start shuffled.
        self.Restart()

    # Clear current song and reshuffle playlist.
    def Restart(self):
        util.log(util.LogSeverity.INFO, f'Restarting playlist "{self._name}".')

        self._cur_src = None
        self._index = 0
        self._ff = datetime.timedelta()
        random.shuffle(self._fs)

    # Returns a new stream that plays the track from the position last left off
    # by any previous stream, plus any subsequent fast-forwarding.
    #
    # Caller is responsible for cleaning up resources for the returned stream.
    async def MakeCurrentTrackStream(self):
        if self._index >= len(self._fs):
            return None

        if self._cur_src:
            util.log(util.LogSeverity.INFO,
                     f'Resuming "{self.current_track_name}".')
            self._cur_src = ResumedAudio(self._fs[self._index],
                                         self._cur_src.elapsed + self._ff)
        else:
            util.log(util.LogSeverity.INFO,
                     f'Starting "{self.current_track_name}".')
            self._cur_src = ResumedAudio(self._fs[self._index], self._ff)

        # When resuming the audio, the current fast-forward amount is already
        # inherited from the previous stream.
        self._ff = datetime.timedelta()

        return self._cur_src

    # Skips forward into the track for subsequent calls to
    # MakeCurrentTrackStream. Existing stream objects are unaffected.
    def FastForward(self, duration):
        if self._index >= len(self._fs):
            return

        self._ff += duration

    def CurrentTrackStreamHasError(self):
        return self._index >= len(
            self._fs) or self._cur_src and self._cur_src.HasError()

    # Move to the next song, reshuffling and starting again if there isn't one.
    def NextTrack(self):
        self._index += 1

        if self._index >= len(self._fs):
            self.Restart()
            return

        self._cur_src = None
        self._ff = datetime.timedelta()

    # Returns a full track listing with a cursor next to the currently-playing
    # track.
    def TrackListing(self):
        titles = [util.file_stem(fn) for fn in self._fs]
        return f'{self._name}:\n\n' + _format_listing(titles, self._index)

    @property
    def name(self):
        return self._name

    @property
    def current_track_name(self):
        return self._fs and util.file_stem(self._fs[self._index])


# Resturns a playlist listing. Puts a cursor next to one "index" playlist.
def playlist_listing(playlists, index):
    return 'Playlists:\n\n' + _format_listing(playlists, index)
