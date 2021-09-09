#!/usr/bin/python3

import asyncio
import datetime
import glob
#
#import discord.ext.commands
#
import util
import playlist


# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def _can_command(ctx):
    return (ctx.author.voice and ctx.voice_client and
            ctx.author.voice.channel == ctx.voice_client.channel)


class ShiloGuild:

    def __init__(self, playlist_config):
        self._playlists = {}
        for name, globs in playlist_config.items():
            self._playlists[name] = playlist.Playlist(
                name, sum([glob.glob(p) for p in globs], []))

        self._playlist = None

        self._next_callbacks = {}

    # Returns true if bot successfully joined author's voice channel.
    async def Join(self, ctx):
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
            if self._playlist:
                self._next_callbacks[self._playlist.name].Cancel()

            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()

        await dest.channel.connect()

        print(f'[INFO] Connected to voice channel "{dest.channel.name}".')
        await ctx.send(f'Connected to the voice channel "{dest.channel.name}".')
        return True

    # Leaves the currently-connected channel.
    async def Leave(self, ctx):
        if not ctx.voice_client:
            await ctx.send('No channel connected!')
            return

        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        # Prevent after-play callback from moving to next song.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()
        ctx.voice_client.stop()

        await ctx.voice_client.disconnect()

        self._playlist = None

        print('[INFO] Disconnected.')
        await ctx.send('Disconnected.')

    # Start playing the current playlist (or the given playlist).
    async def Start(self, ctx, playlist_name=None, restart=False):
        if not await self.Join(ctx):
            return

        auto_name = playlist_name or (self._playlist.name
                                      if self._playlist else None)
        if not auto_name:
            print('[WARNING] Can\'t start: no playlist specified.')
            await ctx.send('Playlist not specified!')
            return

        if auto_name not in self._playlists:
            print(f'[WARNING] Playlist "{auto_name}" doesn\'t exist.')
            await ctx.send(f'Playlist "{auto_name}" doesn\'t exist!')
            return
        playlist = self._playlists[auto_name]

        await ctx.send(f'Playing playlist "{auto_name}".')

        if restart:
            playlist.Restart()

        # Race: "next song" callback executes before we've started the new stream.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()

        await self._PlayCurrent(ctx, playlist)

        print('[INFO] Playback started.')
        await ctx.send(f'Playing "{playlist.current_track_name}".')

    # Restart the current (or a given) playlist.
    async def Restart(self, ctx, playlist_name=None):
        if not playlist_name and not self._playlist:
            print('[WARNING] Tried implicit restart with no ' +
                  'previous playlist.')
            await ctx.send('No playlist to restart!')
            return

        auto_name = playlist_name or (self._playlist.name
                                      if self._playlist else None)
        await self.Start(ctx, auto_name, True)

    # Stop the currently-playing playlist.
    async def Stop(self, ctx):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            print('[WARNING] Tried to stop with nothing playing.')
            await ctx.send('Nothing to stop!')
            return

        # Needed to stop the after-play callback from starting the next song.
        self._next_callbacks[self._playlist.name].Cancel()
        ctx.voice_client.stop()

        print(f'[INFO] Playback of "{self._playlist.current_track_name}"' +
              'stopped.')
        await ctx.send(f'Stopping playlist "{self._playlist.name}".')

    # Move to the next track in the current playlist.
    async def Next(self, ctx):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            print('[WARNING] Tried to skip with nothing playing.')
            await ctx.send('Nothing to skip!')
            return

        # The after-play callback will automatically start playing the next song.
        print('[INFO] Skipping to next.')
        ctx.voice_client.stop()

    # Fast-forward the current song.
    async def FastForward(self, ctx, interval_str):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            print('[WARNING] Tried to fast-forward with nothing playing.')
            await ctx.send('Nothing to fast-forward!')
            return

        interval = util.parse_interval(interval_str)
        if not interval:
            await ctx.send(f'Couldn\'t understand interval "{interval_str}"!')
            print('[WARNING] Cannot fast-forward by bad interval' +
                  f'"{interval_str}".')
            return

        # Race: "next song" callback executes before we've started the new stream.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()

        await self._PlayCurrent(ctx, self._playlist, skip=interval)

        print(f'[INFO] Fast-forwarding by {str(interval)}.')
        await ctx.send('Fast-forwarding ' +
                       f'"{self._playlist.current_track_name}".')

    # List playlists or the tracks in an individual playlist.
    async def List(self, ctx, playlist_name=None):
        # Print playlist list.
        if not playlist_name:
            current_name = self._playlist.name if self._playlist else None
            await ctx.send(
                playlist.print_playlists(self._playlists, current_name))
            return

        # Print specific playlist.
        if playlist_name not in self._playlists:
            print('[WARNING] Trying to print non-existent playlist ' +
                  f'"{playlist_name}".')
            await ctx.send(f'No playlist "{playlist_name}"!')
            return

        await ctx.send(self._playlists[playlist_name].PrintTracks())

    # Play the current entry from the given playlist over the bot voice channel.
    # Bot must be connected to some voice channel.
    async def _PlayCurrent(self, ctx, playlist, skip=datetime.timedelta()):
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

        callback = util.CancellableCoroutine(self._NextTrack(ctx, playlist))

        def schedule_next_track(ctx, callback, error):
            if not ctx.voice_client:
                return

            future = asyncio.run_coroutine_threadsafe(callback.Run(),
                                                      ctx.voice_client.loop)
            future.result()

        after = lambda e, c=ctx, cb=callback: schedule_next_track(c, cb, e)

        ctx.voice_client.play(stream, after=after)

        # Update for !next, !skip etc.
        self._playlist = playlist
        self._next_callbacks[playlist.name] = callback

    # Play the next track of the given playlist.
    async def _NextTrack(self, ctx, playlist):
        playlist.NextTrack()

        await self._PlayCurrent(ctx, playlist)

        print('[INFO] Playback started.')
        await ctx.send(f'Playing "{playlist.current_track_name}".')
