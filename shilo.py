#!/usr/bin/python3

import asyncio
import datetime
import glob
import json

import discord.ext.commands

import util
import playlist

CONFIG_FILE = 'shilo.json'

# Read config.

g_config = json.loads(open(CONFIG_FILE, 'r').read())

# Load playlists.

g_playlists = {}
for name, globs in g_config['playlists'].items():
    g_playlists[name] = playlist.Playlist(name, sum([glob.glob(p) for p in globs], []))
g_playlist = None

# Store callbacks used to load next songs. Used to cancel them when e.g. the
# playlist is stopped.
g_next_callbacks = {}

# Define bot.

g_bot = discord.ext.commands.Bot(command_prefix='!')

# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def can_command(ctx):
    return (ctx.author.voice and ctx.voice_client and
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
            g_next_callbacks[g_playlist.name].Cancel()

        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()

    await dest.channel.connect()

    print(f'[INFO] Connected to voice channel "{dest.channel.name}".')
    await ctx.send(f'Connected to the voice channel "{dest.channel.name}".')
    return True

# Leaves the currently-connected channel.
@g_bot.command(name='leave')
async def leave(ctx):
    global g_playlist

    if not ctx.voice_client:
        await ctx.send(f'No channel connected!')
        return

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    # Prevent after-play callback from moving to next song.
    if g_playlist:
        g_next_callbacks[g_playlist.name].Cancel()
    ctx.voice_client.stop()

    await ctx.voice_client.disconnect()

    g_playlist = None

    print(f'[INFO] Disconnected.')
    await ctx.send(f'Disconnected.')

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

    ctx.voice_client.stop()

    async def next_track(ctx, playlist):
        playlist.NextTrack()

        await play_current(ctx, playlist)

        print(f'[INFO] Playback started.')
        await ctx.send(f'Playing "{playlist.current_track_name}".')

    callback = util.CancellableCoroutine(next_track(ctx, playlist))
    def schedule_next_track(ctx, callback, error):
        if not ctx.voice_client:
            return

        future = asyncio.run_coroutine_threadsafe(callback.Run(), ctx.voice_client.loop)
        future.result()
    after = lambda e, c=ctx, cb=callback: schedule_next_track(c, cb, e)

    ctx.voice_client.play(stream, after=after)

    # Update for !next, !skip etc.
    g_playlist = playlist
    g_next_callbacks[playlist.name] = callback


@g_bot.command(name='start')
async def start(ctx, playlist_name=None, restart=False):
    if not await join(ctx):
        return

    auto_name = playlist_name or (g_playlist.name if g_playlist else None)
    if not auto_name:
        print(f'[WARNING] Can\'t start: no playlist specified.')
        await ctx.send(f'Playlist not specified!')
        return

    if auto_name not in g_playlists:
        print(f'[WARNING] Playlist "{auto_name}" doesn\'t exist.')
        await ctx.send(f'Playlist "{auto_name}" doesn\'t exist!')
        return
    playlist = g_playlists[auto_name]

    await ctx.send(f'Playing playlist "{auto_name}".')

    if restart:
        playlist.Restart()

    # Race: "next song" callback executes before we've started the new stream.
    if g_playlist:
        g_next_callbacks[g_playlist.name].Cancel()

    await play_current(ctx, playlist)

    print(f'[INFO] Playback started.')
    await ctx.send(f'Playing "{playlist.current_track_name}".')

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

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to stop with nothing playing.')
        await ctx.send(f'Nothing to stop!')
        return

    # Needed to stop the after-play callback from starting the next song.
    g_next_callbacks[g_playlist.name].Cancel()
    ctx.voice_client.stop()

    print(f'[INFO] Playback of "{g_playlist.current_track_name}" stopped.')
    await ctx.send(f'Stopping playlist "{g_playlist.name}".')

@g_bot.command(name='next')
async def next(ctx):
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

@g_bot.command(name='ff')
async def ff(ctx, interval_str):
    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {g_bot.user.name}!')
        return

    if not ctx.voice_client.is_playing():
        print(f'[WARNING] Tried to fast-forward with nothing playing.')
        await ctx.send(f'Nothing to fast-forward!')
        return

    interval = util.parse_interval(interval_str)
    if not interval:
        await ctx.send(f'Couldn\'t understand interval "{interval_str}"!')
        print(f'[WARNING] Cannot fast-forward by bad interval "{interval_str}".')
        return

    # Race: "next song" callback executes before we've started the new stream.
    if g_playlist:
        g_next_callbacks[g_playlist.name].Cancel()

    await play_current(ctx, g_playlist, skip=interval)
    print(f'[INFO] Fast-forwarding by {str(interval)}.')
    await ctx.send(f'Fast-forwarding "{g_playlist.current_track_name}".')

@g_bot.command(name='list')
async def list(ctx, playlist_name=None):
    # Print playlist list.
    if not playlist_name:
        current_name = g_playlist.name if g_playlist else None
        await ctx.send(playlist.print_playlists(g_playlists, current_name))
        return

    # Print specific playlist.
    if playlist_name not in g_playlists:
        print('[WARNING] Trying to print non-existent playlist "{playlist_name}".')
        await ctx.send(f'No playlist "{playlist_name}"!')
        return

    await ctx.send(g_playlists[playlist_name].PrintTracks())

# Run bot.

g_bot.run(g_config['token'])
