#!/usr/bin/python3

import asyncio
import datetime
import discord
import discord.ext.commands
import functools
import glob
import json
import os
import random

CONFIG_FILE = 'shilo.json'
READ_AUDIO_CHUNK_MS = 20

def file_stem(path):
    basename = os.path.basename(path)
    return basename.split('.')[0]

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

    # Return the current audio source, or load it if it isn't initialised.
    # Caller is responsible for cleaning up resources for the returned stream.
    async def MakeCurrentStream(self):
        if self._index >= len(self._fs):
            return None

        if self._cur_src:
            print(f'[INFO] Resuming "{self.CurrentName()}".')
            self._cur_src.cleanup()
            self._cur_src = ElapsedAudio(self._fs[self._index], self._cur_src.elapsed_ms)
        else:
            print(f'[INFO] Starting "{self.CurrentName()}".')
            self._cur_src = ElapsedAudio(self._fs[self._index])

        return self._cur_src

    # Move to the next song, reshuffling and starting again if there isn't one.
    def Next(self):
        self._index += 1

        if self._index >= len(self._fs):
            self.Restart()
            return

        self._cur_src = None

    def CurrentIndex(self):
        return self._index

    def CurrentName(self):
        return file_stem(self._fs[self._index]) if self._fs else None

# Read config.

config = json.loads(open(CONFIG_FILE, 'r').read())

playlists = {}
for name, globs in config['playlists'].items():
    playlists[name] = Playlist(name, sum([glob.glob(p) for p in globs], []))

# Define bot.

bot = discord.ext.commands.Bot(command_prefix='!')

# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def can_command(ctx):
    return ctx.author.voice and (not ctx.voice_client or
           ctx.author.voice.channel == ctx.voice_client.channel)

@bot.event
async def on_ready():
    print(f'[INFO] {bot.user.name} connected.')

# Returns true if bot successfully joined author's voice channel.
@bot.command(name='join')
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
        await ctx.voice_client.disconnect()

    await dest.channel.connect()
    print(f'[INFO] Joined voice channel "{dest.channel.name}".')
    await ctx.send(f'Joined the voice channel "{dest.channel.name}".')
    return True

async def play_next(ctx, playlist):
    playlist.Next()
    await play_current(ctx, playlist)

# Play the current entry from the given playlist over the bot voice channel.
# Bot must be connected to some voice channel.
async def play_current(ctx, playlist):
    if not playlist.CurrentName():
        print(f'[WARNING] Tried to play empty playlist "{playlist_name}".')
        await ctx.send(f'Couldn\'t play empty playlist "{playlist_name}"!')
        return

    stream = await playlist.MakeCurrentStream()
    if not stream:
        print(f'[ERROR] Couldn\'t play "{playlist.CurrentName()}".')
        await ctx.send(f'Couldn\'t play "{playlist.CurrentName()}"!')
        return

    print(f'[INFO] Playback started.')
    await ctx.send(f'Playing "{playlist.CurrentName()}".')

    def play_next_coro(in_ctx, in_playlist, error):
        coro = play_next(in_ctx, in_playlist)
        fut = asyncio.run_coroutine_threadsafe(coro, ctx.voice_client.loop)
        fut.result()
    callback = functools.partial(play_next_coro, ctx, playlist)

    ctx.voice_client.stop()
    ctx.voice_client.play(stream, after=callback)

@bot.command(name='start')
async def start(ctx, playlist_name, restart=False):
    if not await join(ctx):
        return

    if playlist_name not in playlists:
        print(f'[WARNING] Playlist "{playlist_name}" doesn\'t exist.')
        await ctx.send(f'Playlist "{playlist_name}" doesn\'t exist!')
        return
    playlist = playlists[playlist_name]

    if restart:
        playlist.Restart()

    await play_current(ctx, playlist)

@bot.command(name='restart')
async def restart(ctx, playlist_name):
    await start(ctx, playlist_name, True)

@bot.command(name='stop')
async def pause(ctx):
    if not await join(ctx):
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to stop with nothing playing.')
        await ctx.send(f'Nothing to stop!')
        return

    print(f'[INFO] Playback stopped.')

    ctx.voice_client.stop()

# Run bot.

bot.run(config['token'])
