#!/usr/bin/python3

import asyncio
import datetime
import glob

import util
import playlist


# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def _can_command(ctx):
    return (ctx.author.voice and ctx.voice_client and
            ctx.author.voice.channel == ctx.voice_client.channel)


# Represents the presence of ShiloBot in one guild. This allows for independent
# playback (e.g. position in playlists) per guild.
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
            await self._Disconnect(ctx.voice_client)

        await dest.channel.connect()

        # Deafen the bot to assure users they aren't being eavesdropped on.
        await ctx.guild.change_voice_state(channel=dest.channel, self_deaf=True)

        util.log(util.LogSeverity.INFO,
                 f'Connected to voice channel "{dest.channel.name}".')
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

        util.log(
            util.LogSeverity.INFO, 'Disconnected from voice channel ' +
            f'"{ctx.voice_client.channel.name}".')

        await self._Disconnect(ctx.voice_client)

        await ctx.send('Disconnected.')

    # Start playing the current playlist (or the given playlist).
    async def Start(self, ctx, playlist_name=None, restart=False):
        if not await self.Join(ctx):
            return

        resolved_name = playlist_name or self._playlist and self._playlist.name
        if not resolved_name:
            util.log(util.LogSeverity.WARNING,
                     'Can\'t start: no playlist specified.')
            await ctx.send('Playlist not specified!')
            return

        if resolved_name not in self._playlists:
            util.log(util.LogSeverity.WARNING,
                     f'Playlist "{resolved_name}" doesn\'t exist.')
            await ctx.send(f'Playlist "{resolved_name}" doesn\'t exist!')
            return
        playlist = self._playlists[resolved_name]

        await ctx.send(f'Playing playlist "{resolved_name}".')

        if restart:
            playlist.Restart()

        # Race: "next song" callback executes before we've started the new stream.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()

        played = await self._PlayCurrent(ctx, playlist)

        if played:
            util.log(util.LogSeverity.INFO, 'Playback started.')
            await ctx.send(f'Playing "{playlist.current_track_name}".')

    # Restart the current (or a given) playlist.
    async def Restart(self, ctx, playlist_name=None):
        if not playlist_name and not self._playlist:
            util.log(util.LogSeverity.WARNING,
                     'Tried implicit restart with no previous playlist.')
            await ctx.send('No playlist to restart!')
            return

        resolved_name = playlist_name or self._playlist and self._playlist.name
        await self.Start(ctx, resolved_name, True)

    # Stop the currently-playing playlist.
    async def Stop(self, ctx):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            util.log(util.LogSeverity.WARNING,
                     'Tried to stop with nothing playing.')
            await ctx.send('Nothing to stop!')
            return

        # Needed to stop the after-play callback from starting the next song.
        self._next_callbacks[self._playlist.name].Cancel()
        ctx.voice_client.stop()

        util.log(util.LogSeverity.INFO,
                 f'Playback of "{self._playlist.current_track_name}" stopped.')
        await ctx.send(f'Stopping playlist "{self._playlist.name}".')

    # Move to the next track in the current playlist.
    async def Next(self, ctx):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not self._playlist:
            util.log(util.LogSeverity.WARNING,
                     'Tried to skip with no playlist active.')
            await ctx.send('Not playlist selected!')
            return

        util.log(util.LogSeverity.INFO, 'Skipping to next.')

        if ctx.voice_client.is_playing():
            # The after-play callback will automatically start playing the next
            # song.
            ctx.voice_client.stop()
        else:
            self._playlist.NextTrack()
            track_name = self._playlist.current_track_name or "next track"
            await ctx.send(f'Loaded "{track_name}".')

    # Fast-forward the current song.
    async def FastForward(self, ctx, interval_str):
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            util.log(util.LogSeverity.WARNING,
                     'Tried to fast-forward with nothing playing.')
            await ctx.send('Nothing to fast-forward!')
            return

        interval = util.parse_interval(interval_str)
        if not interval:
            await ctx.send(f'Couldn\'t understand interval "{interval_str}"!')
            util.log(util.LogSeverity.WARNING,
                     f'Cannot fast-forward by bad interval "{interval_str}".')
            return

        # Race: "next song" callback executes before we've started the new stream.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()

        played = await self._PlayCurrent(ctx, self._playlist, skip=interval)

        if played:
            util.log(util.LogSeverity.INFO,
                     f'Fast-forwarding by {str(interval)}.')
            await ctx.send('Fast-forwarding ' +
                           f'"{self._playlist.current_track_name}".')

    # List playlists or the tracks in an individual playlist.
    async def List(self, ctx, playlist_name=None):
        # Print playlist list.
        if not playlist_name:
            playlist_names = list(self._playlists.keys())
            current_index = self._playlist and playlist_names.index(
                self._playlist.name) or -1
            table = playlist.playlist_listing(playlist_names, current_index)
            await ctx.send(f'```\n{table}\n```')
            return

        # Print specific playlist.
        if playlist_name not in self._playlists:
            util.log(
                util.LogSeverity.WARNING,
                f'Trying to print non-existent playlist "{playlist_name}".')
            await ctx.send(f'No playlist "{playlist_name}"!')
            return

        await ctx.send(
            f'```\n{self._playlists[playlist_name].TrackListing()}\n```')

    # Leave the voice channel once everyone else has.
    async def OnVoiceStateUpdate(self, bot_voice_client, before, after):
        bot_channel = bot_voice_client.channel

        # Nothing to do if:
        #   1) We aren't connected to a voice channel, or
        #   2) The user isn't leaving our channel.
        if (not bot_channel or before.channel != bot_channel or
                after.channel == bot_channel):
            return

        # Only leave if there are no users left.
        if [m for m in bot_channel.members if not m.bot]:
            return

        util.log(
            util.LogSeverity.INFO,
            f'Disconnected from empty voice channel "{bot_channel.name}".')

        await self._Disconnect(bot_voice_client)

    # Play the current entry from the given playlist over the bot voice channel.
    # Bot must be connected to some voice channel.
    async def _PlayCurrent(self, ctx, playlist, skip=datetime.timedelta()):
        if not playlist.current_track_name:
            util.log(util.LogSeverity.WARNING,
                     f'Tried to play empty playlist "{playlist.name}".')
            await ctx.send(f'Couldn\'t play empty playlist "{playlist.name}"!')
            return False

        stream = await playlist.MakeCurrentTrackStream(skip)
        if not stream:
            util.log(util.LogSeverity.ERROR,
                     f'Couldn\'t play "{playlist.current_track_name}".')
            await ctx.send(f'Couldn\'t play "{playlist.current_track_name}"!')
            return False

        ctx.voice_client.stop()

        callback = util.CancellableCoroutine(self._PlayNextTrack(ctx, playlist))

        def schedule_next_track(ctx, callback, playlist, error):
            if playlist.CurrentTrackStreamHasError():
                callback.Cancel()
                print_err = ctx.send(
                    'Error playing ' +
                    f'"{playlist.current_track_name}". Stopping')
                future = asyncio.run_coroutine_threadsafe(
                    print_err, ctx.voice_client.loop)
            else:
                future = asyncio.run_coroutine_threadsafe(
                    callback.Run(), ctx.voice_client.loop)
            future.result()

        after = lambda e, c=ctx, cb=callback, p=playlist: schedule_next_track(
            c, cb, p, e)

        ctx.voice_client.play(stream, after=after)

        # Update for !next, !skip etc.
        self._playlist = playlist
        self._next_callbacks[playlist.name] = callback

        return True

    # Play the next track of the given playlist.
    async def _PlayNextTrack(self, ctx, playlist):
        playlist.NextTrack()

        played = await self._PlayCurrent(ctx, playlist)

        if played:
            util.log(util.LogSeverity.INFO, 'Playback started.')
            await ctx.send(f'Playing "{playlist.current_track_name}".')

    # Stop the currently playing song, de-select the current playlist and
    # disconnect from the current voice channel.
    async def _Disconnect(self, voice_client):
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()
        voice_client.stop()
        self._playlist = None

        await voice_client.disconnect()
