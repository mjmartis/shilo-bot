#!/usr/bin/python3

import asyncio
import datetime
import discord
import discord.ext.commands
import glob
import json
import os
import random

CONFIG_FILE = 'shilo.json'
READ_AUDIO_CHUNK_TIME = datetime.timedelta(milliseconds=20)

PRINT_INDEX_WIDTH = 3
PRINT_TRACK_WIDTH = 40

# Wrapper around FFmpegOpusAudio that counts the number of milliseconds
# streamed so far.
class ElapsedAudio(discord.FFmpegOpusAudio):
    def __init__(self, filename, elapsed=datetime.timedelta()):
        # TODO: foward args if more sophisticated construction is needed.
        super().__init__(filename, options=f'-ss {str(elapsed)}')

        self._elapsed = elapsed

    def read(self):
        self._elapsed += READ_AUDIO_CHUNK_TIME
        return super().read()

    @property
    def elapsed(self):
        return self._elapsed

def file_stem(path):
    basename = os.path.basename(path)
    return basename.split('.')[0]

# Maintains a cursor in a list of music files and exposes an audio stream for
# the current file.
class Playlist:
    def __init__(self, name, fs):
        # Public; used by clients to determine when to automatically skip to
        # the next song.
        self.is_stopped = False

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
            self._cur_src.cleanup()
            self._cur_src = ElapsedAudio(self._fs[self._index], self._cur_src.elapsed + skip)
        else:
            print(f'[INFO] Starting "{self.current_track_name}".')
            self._cur_src = ElapsedAudio(self._fs[self._index])

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
            num = (str(i+1) + ".").ljust(PRINT_INDEX_WIDTH)
            track = file_stem(fn).ljust(PRINT_TRACK_WIDTH)
            marker = ' [<]' if i == self._index else ''
            s += f'\t{num} {track}{marker}\n'

        return s

    @property
    def name(self):
        return self._name

    @property
    def current_track_name(self):
        return file_stem(self._fs[self._index]) if self._fs else None

# Read config.

g_config = json.loads(open(CONFIG_FILE, 'r').read())

# Load playlists.

g_playlists = {}
for name, globs in g_config['playlists'].items():
    g_playlists[name] = Playlist(name, sum([glob.glob(p) for p in globs], []))
g_playlist = None

# Define bot.

g_bot = discord.ext.commands.Bot(command_prefix='!')

# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def can_command(ctx):
    return ctx.author.voice and (not ctx.voice_client or
           ctx.author.voice.channel == ctx.voice_client.channel)

@g_bot.event
async def on_ready():
    print(f'[INFO] {g_bot.user.name} connected.')

# Returns true if bot successfully joined author's voice channel.
@g_bot.command(name='join')
async def join(ctx):
    dest = ctx.author.voice

    # No channel to connect to.
    if not dest:
        await ctx.send('You must connect to a voice channel!')
        return False

    # Already connected to correct channel.
    if ctx.voice_client and ctx.voice_client.channel == dest.channel:
        return True

    if ctx.voice_client:
        # Prevent after-play callback from moving to next song.
        if g_playlist:
            g_playlist.is_stopped = True

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()

    await dest.channel.connect()

    print(f'[INFO] Joined voice channel "{dest.channel.name}".')
    await ctx.send(f'Joined the voice channel "{dest.channel.name}".')
    return True

# Play the current entry from the given playlist over the bot voice channel.
# Bot must be connected to some voice channel.
async def play_current(ctx, playlist, skip=datetime.timedelta()):
    global g_playlist

    if not playlist.current_track_name:
        print(f'[WARNING] Tried to play empty playlist "{playlist.name}".')
        await ctx.send(f'Couldn\'t play empty playlist "{playlist.name}"!')
        return

    stream = await playlist.MakeCurrentTrackStream(skip)
    if not stream:
        print(f'[ERROR] Couldn\'t play "{playlist.current_track_name}".')
        await ctx.send(f'Couldn\'t play "{playlist.current_track_name}"!')
        return

    def play_next(ctx, playlist, error):
        # Don't continue to next song when this callback has been executed
        # because of e.g. the !stop command.
        if playlist.is_stopped:
            return

        playlist.NextTrack()

        # Schedule coroutine.
        coro = play_current(ctx, playlist)
        fut = asyncio.run_coroutine_threadsafe(coro, ctx.voice_client.loop)
        fut.result()
    callback = lambda e, c=ctx, p=playlist: play_next(c, p, e)

    # Needed to stop the after-play callback from starting the next song.
    if g_playlist:
        g_playlist.is_stopped = True
    ctx.voice_client.stop()

    print(f'[INFO] Playback started.')
    await ctx.send(f'Playing "{playlist.current_track_name}".')

    playlist.is_stopped = False
    ctx.voice_client.play(stream, after=callback)

    # Update for !next, !skip etc.
    g_playlist = playlist


@g_bot.command(name='start')
async def start(ctx, playlist_name, restart=False):
    if not await join(ctx):
        return

    if playlist_name not in g_playlists:
        print(f'[WARNING] Playlist "{playlist_name}" doesn\'t exist.')
        await ctx.send(f'Playlist "{playlist_name}" doesn\'t exist!')
        return
    playlist = g_playlists[playlist_name]

    await ctx.send(f'Playing playlist "{playlist_name}".')

    if restart:
        playlist.Restart()

    await play_current(ctx, playlist)

@g_bot.command(name='restart')
async def restart(ctx, playlist_name=None):
    if not playlist_name and not g_playlist:
        print(f'[WARNING] Tried implicit restart with no previous playlist.')
        await ctx.send('No playlist to restart!')
        return

    auto_name = playlist_name or (g_playlist.name if g_playlist else None)
    await start(ctx, auto_name, True)

@g_bot.command(name='stop')
async def stop(ctx):
    global g_playlists

    if not await join(ctx):
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to stop with nothing playing.')
        await ctx.send(f'Nothing to stop!')
        return

    # Needed to stop the after-play callback from starting the next song.
    g_playlist.is_stopped = True
    ctx.voice_client.stop()

    print(f'[INFO] Playback of "{g_playlist.current_track_name}" stopped.')
    await ctx.send(f'Stopping playlist "{g_playlist.name}".')

@g_bot.command(name='next')
async def next(ctx):
    if not await join(ctx):
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to skip with nothing playing.')
        await ctx.send(f'Nothing to skip!')
        return

    # The after-play callback will automatically start playing the next song.
    print(f'[INFO] Skipping to next.')
    ctx.voice_client.stop()

def parse_interval(s):
    suffix = s.lstrip('0123456789.')
    unit = suffix.strip().lower()
    num = float(s[:-len(suffix)].strip())

    INTERVALS = {
        "s": datetime.timedelta(seconds=1),
        "sec": datetime.timedelta(seconds=1),
        "secs": datetime.timedelta(seconds=1),
        "seconds": datetime.timedelta(seconds=1),
        "m": datetime.timedelta(minutes=1),
        "min": datetime.timedelta(minutes=1),
        "mins": datetime.timedelta(minutes=1),
        "minutes": datetime.timedelta(minutes=1),
        "hr": datetime.timedelta(hours=1),
        "hrs": datetime.timedelta(hours=1),
        "hours": datetime.timedelta(hours=1),
    }

    if unit not in INTERVALS:
        print(f'[WARNING] Couldn\'t parse interval "{s}".')
        return datetime.timedelta()

    return num * INTERVALS[unit]

@g_bot.command(name='ff')
async def ff(ctx, interval_str):
    if not await join(ctx):
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to fast-forward with nothing playing.')
        await ctx.send(f'Nothing to fast-forward!')
        return

    interval = parse_interval(interval_str)

    print(f'[INFO] Fast-forwarding by {str(interval)}')

    await play_current(ctx, g_playlist, skip=interval)

def print_playlists():
    target_name = g_playlist.name if g_playlist else None

    s = "Playlists:\n"
    for i, name in enumerate(g_playlists.keys()):
        num = (str(i+1) + '.').ljust(PRINT_INDEX_WIDTH)
        title = name.ljust(PRINT_TRACK_WIDTH)
        marker = ' [<]' if name == target_name else ''

        s += f'\t{num} {title}{marker}\n'

    return s

@g_bot.command(name='list')
async def list(ctx, playlist_name=None):
    if not await join(ctx):
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    # Print playlist list.
    if not playlist_name:
        await ctx.send(print_playlists())
        return

    # Print specific playlist.
    if playlist_name not in g_playlists:
        print('[WARNING] Trying to print non-existent playlist "{playlist_name}".')
        await ctx.send(f'No playlist "{playlist_name}"!')
        return

    await ctx.send(g_playlists[playlist_name].PrintTracks())

# Run bot.

g_bot.run(g_config['token'])
