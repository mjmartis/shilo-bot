#!/usr/bin/python3

import datetime
import random

import discord

import util

READ_AUDIO_CHUNK_TIME = datetime.timedelta(milliseconds=20)

PRINT_INDEX_WIDTH = 3
PRINT_TRACK_WIDTH = 40


# Wrapper around FFmpegOpusAudio that counts the number of milliseconds
# streamed so far.
class ResumedAudio(discord.FFmpegOpusAudio):

    def __init__(self, filename, elapsed=datetime.timedelta()):
        # TODO: foward args if more sophisticated construction is needed.
        super().__init__(filename, before_options=f'-ss {str(elapsed)}')

        self._elapsed = elapsed

    def read(self):
        self._elapsed += READ_AUDIO_CHUNK_TIME
        return super().read()

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

        # Start shuffled.
        self.Restart()

    # Clear current song and reshuffle playlist.
    def Restart(self):
        print(f'[INFO] Restarting playlist "{self._name}".')

        self._cur_src = None
        random.shuffle(self._fs)
        self._index = 0

    # Returns a new stream that plays the track from the position last left off
    # by any previous stream. Optionally takes a timedelta to skip further
    # forward.
    #
    # Caller is responsible for cleaning up resources for the returned stream.
    async def MakeCurrentTrackStream(self, skip=datetime.timedelta()):
        if self._index >= len(self._fs):
            return None

        if self._cur_src:
            print(f'[INFO] Resuming "{self.current_track_name}".')
            self._cur_src = ResumedAudio(self._fs[self._index],
                                         self._cur_src.elapsed + skip)
        else:
            print(f'[INFO] Starting "{self.current_track_name}".')
            self._cur_src = ResumedAudio(self._fs[self._index])

        return self._cur_src

    # Move to the next song, reshuffling and starting again if there isn't one.
    def NextTrack(self):
        self._index += 1

        if self._index >= len(self._fs):
            self.Restart()
            return

        self._cur_src = None

    # Print out a full track listing.
    def PrintTracks(self):
        s = f'{self._name}:\n'
        for i, fn in enumerate(self._fs):
            num = (str(i + 1) + ".").ljust(PRINT_INDEX_WIDTH)
            track = util.file_stem(fn).ljust(PRINT_TRACK_WIDTH)
            marker = ' [<]' if i == self._index else ''
            s += f'\t{num} {track}{marker}\n'

        return s

    @property
    def name(self):
        return self._name

    @property
    def current_track_name(self):
        return util.file_stem(self._fs[self._index]) if self._fs else None


# Prints a playlist listing. Puts a cursor next to one "current" playlist.
def print_playlists(playlists, current_name):
    s = "Playlists:\n"
    for i, name in enumerate(playlists.keys()):
        num = (str(i + 1) + '.').ljust(PRINT_INDEX_WIDTH)
        title = name.ljust(PRINT_TRACK_WIDTH)
        marker = ' [<]' if name == current_name else ''

        s += f'\t{num} {title}{marker}\n'

    return s
