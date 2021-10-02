#!/usr/bin/python3

import asyncio
import concurrent.futures as futures
import datetime
import glob

import discord
import discord.ext.commands as dcoms

import utils
import playlists

from typing import Awaitable, cast, Callable, Optional


# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def _can_command(ctx: dcoms.Context) -> bool:
    return (ctx.author.voice and ctx.voice_client and
            ctx.author.voice.channel == ctx.voice_client.channel)


# Returns the quoted name of the current track of the given playlist, or else
# the unquoted word "track".
def _track_name(playlist: Optional[playlists.Playlist]) -> str:
    return (f'"{playlist.current_track_name}"' if playlist is not None and
            playlist.current_track_name else 'track')


# Represents the presence of ShiloBot in one guild. This allows for independent
# playback (e.g. position in playlists) per guild.
class ShiloGuild:

    def __init__(self, playlist_config: dict[str, list[str]]):
        self._playlists: dict[str, playlists.Playlist] = {}
        for name, globs in playlist_config.items():
            self._playlists[name] = playlists.Playlist(
                name, sum([glob.glob(p) for p in globs], []))

        self._playlist: Optional[playlists.Playlist] = None

        self._next_callbacks: dict[str, utils.CancellableCoroutine] = {}

    # Returns true if bot successfully joined author's voice channel.
    async def Join(self, ctx: dcoms.Context) -> bool:
        dest: Optional[discord.VoiceState] = ctx.author.voice

        # No channel to connect to.
        if not dest:
            await ctx.send('You must connect to a voice channel!')
            return False

        # Already connected to correct channel.
        if ctx.voice_client and ctx.voice_client.channel == dest.channel:
            return True

        if ctx.voice_client:
            await self._Disconnect(ctx.voice_client)

        dest_channel: discord.VoiceChannel = cast(discord.VoiceChannel,
                                                  dest.channel)
        await dest_channel.connect()

        # Deafen the bot to assure users they aren't being eavesdropped on.
        await ctx.guild.change_voice_state(channel=dest_channel, self_deaf=True)

        utils.log(utils.LogSeverity.INFO,
                  f'Connected to voice channel "{dest_channel.name}".')
        await ctx.send(f'Connected to the voice channel "{dest_channel.name}".')
        return True

    # Leaves the currently-connected channel.
    async def Leave(self, ctx: dcoms.Context) -> None:
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        utils.log(
            utils.LogSeverity.INFO, 'Disconnected from voice channel ' +
            f'"{ctx.voice_client.channel.name}".')

        await self._Disconnect(ctx.voice_client)

        await ctx.send('Disconnected.')

    # Start playing the current playlist (or the given playlist).
    async def Start(self, ctx, playlist_name=None, restart=False) -> None:
        if not await self.Join(ctx):
            return

        resolved_name: Optional[str] = (self._playlist.name
                                        if self._playlist and not playlist_name
                                        else playlist_name)
        if not resolved_name:
            utils.log(utils.LogSeverity.WARNING,
                      'Can\'t start: no playlist specified.')
            await ctx.send('Playlist not specified!')
            return

        if resolved_name not in self._playlists:
            utils.log(utils.LogSeverity.WARNING,
                      f'Playlist "{resolved_name}" doesn\'t exist.')
            await ctx.send(f'Playlist "{resolved_name}" doesn\'t exist!')
            return
        playlist: playlists.Playlist = self._playlists[resolved_name]

        await ctx.send(f'Playing playlist "{resolved_name}".')

        if restart:
            playlist.Restart()

        # Race: "next song" callback executes before we've started the new stream.
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()

        await self._PlayCurrent(ctx, playlist)

    # Restart the current (or a given) playlist.
    async def Restart(self,
                      ctx: dcoms.Context,
                      playlist_name: Optional[str] = None) -> None:
        await self.Start(ctx, playlist_name, True)

    # Stop the currently-playing playlist.
    async def Stop(self, ctx: dcoms.Context) -> None:
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return

        if not ctx.voice_client.is_playing():
            utils.log(utils.LogSeverity.WARNING,
                      'Tried to stop with nothing playing.')
            await ctx.send('Nothing to stop!')
            return

        # Playing => active playlist.
        assert self._playlist is not None

        # Needed to stop the after-play callback from starting the next song.
        self._next_callbacks[self._playlist.name].Cancel()
        ctx.voice_client.stop()

        utils.log(utils.LogSeverity.INFO,
                  f'Playback of {_track_name(self._playlist)} stopped.')
        await ctx.send(f'Stopping playlist "{self._playlist.name}".')

    # Move to the next track in the current playlist.
    async def Next(self, ctx) -> None:
        if not await self._ReportActivePlaylistControl(ctx):
            return
        assert self._playlist is not None

        utils.log(utils.LogSeverity.INFO, 'Skipping to next.')

        if ctx.voice_client.is_playing():
            # The after-play callback will automatically start playing the next
            # song.
            ctx.voice_client.stop()
        else:
            self._playlist.NextTrack()
            await ctx.send(f'Loaded {_track_name(self._playlist)}.')

    # Fast-forward the current song.
    async def FastForward(self, ctx: dcoms.Context, interval_str: str) -> None:
        if not await self._ReportActivePlaylistControl(ctx):
            return
        assert self._playlist is not None

        interval: Optional[datetime.timedelta] = utils.parse_interval(
            interval_str)
        if not interval:
            await ctx.send(f'Couldn\'t understand interval "{interval_str}"!')
            utils.log(utils.LogSeverity.WARNING,
                      f'Cannot fast-forward by bad interval "{interval_str}".')
            return

        self._playlist.FastForward(interval)

        utils.log(utils.LogSeverity.INFO,
                  f'Fast-forwarding by {str(interval)}.')
        await ctx.send(f'Fast-forwarding {_track_name(self._playlist)}.')

        if ctx.voice_client.is_playing():
            # Race: "next song" callback executes before we've started the new
            # stream.
            self._next_callbacks[self._playlist.name].Cancel()

            await self._PlayCurrent(ctx, self._playlist)

    # List playlists or the tracks in an individual playlist.
    async def List(self,
                   ctx: dcoms.Context,
                   playlist_name: Optional[str] = None) -> None:
        # Print playlist list.
        if not playlist_name:
            playlist_names: list[str] = list(self._playlists.keys())
            current_index: int = playlist_names.index(
                self._playlist.name) if self._playlist else -1
            table: str = playlists.playlist_listing(playlist_names,
                                                    current_index)
            await ctx.send(f'```\n{table}\n```')
            return

        # Print specific playlist.
        if playlist_name not in self._playlists:
            utils.log(
                utils.LogSeverity.WARNING,
                f'Trying to print non-existent playlist "{playlist_name}".')
            await ctx.send(f'No playlist "{playlist_name}"!')
            return

        await ctx.send(
            f'```\n{self._playlists[playlist_name].TrackListing()}\n```')

    # Leave the voice channel once everyone else has.
    async def OnVoiceStateUpdate(self, bot_voice_client: discord.VoiceClient,
                                 before: discord.VoiceState,
                                 after: discord.VoiceState) -> None:
        # TODO: find out how to annotate with a Connectable type.
        bot_channel = cast(discord.VoiceChannel, bot_voice_client.channel)

        # Nothing to do if:
        #   1) We aren't connected to a voice channel, or
        #   2) The user isn't leaving our channel.
        if (not bot_channel or before.channel != bot_channel or
                after.channel == bot_channel):
            return

        # Only leave if there are no users left.
        if [m for m in bot_channel.members if not m.bot]:
            return

        utils.log(
            utils.LogSeverity.INFO,
            f'Disconnected from empty voice channel "{bot_channel.name}".')

        await self._Disconnect(bot_voice_client)

    # Play the current entry from the given playlist over the bot voice channel.
    # Bot must be connected to some voice channel.
    async def _PlayCurrent(self, ctx, playlist) -> None:
        if not playlist.current_track_name:
            utils.log(utils.LogSeverity.WARNING,
                      f'Tried to play empty playlist "{playlist.name}".')
            await ctx.send(f'Couldn\'t play empty playlist "{playlist.name}"!')
            return

        stream: playlists.ResumedAudio = \
            await playlist.MakeCurrentTrackStream()
        if not stream:
            utils.log(utils.LogSeverity.ERROR,
                      f'Couldn\'t play {_track_name(playlist)}.')
            await ctx.send(f'Couldn\'t play {_track_name(playlist)}!')
            return

        ctx.voice_client.stop()

        callback: utils.CancellableCoroutine = utils.CancellableCoroutine(
            self._PlayNextTrack(ctx, playlist))

        def schedule_next_track(
                error: Optional[str],
                ctx: dcoms.Context = ctx,
                callback: utils.CancellableCoroutine = callback,
                playlist: playlists.Playlist = playlist) -> None:
            if not ctx.voice_client:
                callback.Cancel()
                return

            if playlist.CurrentTrackStreamHasError():
                callback.Cancel()
                print_err: Awaitable[None] = ctx.send(
                    f'Error playing {_track_name(playlist)}. Stopping.')
                future: futures.Future = asyncio.run_coroutine_threadsafe(
                    print_err, ctx.voice_client.loop)
            else:
                future = asyncio.run_coroutine_threadsafe(
                    callback.Run(), ctx.voice_client.loop)

            future.result()

        ctx.voice_client.play(stream, after=schedule_next_track)

        # Update for !next, !skip etc.
        self._playlist = playlist
        self._next_callbacks[playlist.name] = callback

        utils.log(utils.LogSeverity.INFO, 'Playback started.')
        await ctx.send(f'Playing {_track_name(playlist)}.')

    # Play the next track of the given playlist.
    async def _PlayNextTrack(self, ctx: dcoms.Context,
                             playlist: playlists.Playlist) -> None:
        playlist.NextTrack()
        await self._PlayCurrent(ctx, playlist)

    # Stop the currently playing song, de-select the current playlist and
    # disconnect from the current voice channel.
    async def _Disconnect(self, voice_client: discord.VoiceClient) -> None:
        if self._playlist:
            self._next_callbacks[self._playlist.name].Cancel()
        voice_client.stop()
        self._playlist = None

        await voice_client.disconnect()

    # Returns true if the current author can command the bot and there is an
    # active playlist. If not, reports to the user.
    async def _ReportActivePlaylistControl(self, ctx: dcoms.Context) -> bool:
        if not _can_command(ctx):
            await ctx.send('You must connect yourself to the same channel ' +
                           f'as {ctx.bot.user.name}!')
            return False

        if not self._playlist:
            utils.log(utils.LogSeverity.WARNING,
                      'Tried to skip or fast-forward with no playlist active.')
            await ctx.send('No playlist selected!')
            return False

        return True
