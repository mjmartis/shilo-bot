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
READ_AUDIO_CHUNK_MS = 20

# Wrapper around FFmpegOpusAudio that counts the number of milliseconds
# streamed so far.
class ElapsedAudio(discord.FFmpegOpusAudio):
    def __init__(self, filename, elapsed_ms=0):
        # TODO: foward args if more sophisticated construction is needed.
        ss = datetime.timedelta(milliseconds=elapsed_ms)
        super().__init__(filename, options=f'-ss {str(ss)}')

        self._elapsed_ms = elapsed_ms

    def read(self):
        self._elapsed_ms += READ_AUDIO_CHUNK_MS
        return super().read()

    @property
    def elapsed_ms(self):
        return self._elapsed_ms

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

    # Return the current audio source, or load it if it isn't initialised.
    # Caller is responsible for cleaning up resources for the returned stream.
    async def MakeCurrentTrackStream(self):
        if self._index >= len(self._fs):
            return None

        if self._cur_src:
            print(f'[INFO] Resuming "{self.current_track_name}".')
            self._cur_src.cleanup()
            self._cur_src = ElapsedAudio(self._fs[self._index], self._cur_src.elapsed_ms)
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
async def play_current(ctx, playlist):
    global g_playlist

    if not playlist.current_track_name:
        print(f'[WARNING] Tried to play empty playlist "{playlist_name}".')
        await ctx.send(f'Couldn\'t play empty playlist "{playlist_name}"!')
        return

    stream = await playlist.MakeCurrentTrackStream()
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

# Run bot.

g_bot.run(g_config['token'])
