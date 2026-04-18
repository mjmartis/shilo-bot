#!/usr/bin/python3

import asyncio
import concurrent.futures as futures
import datetime
import enum
import glob
import logging

from typing import cast, Optional

import discord
import discord.commands.context as dctx

import utils
import playlists


class JoinResult(enum.Enum):
  FAIL = enum.auto()
  SUCCESS = enum.auto()
  ALREADY_JOINED = enum.auto()


def _can_command(ctx: dctx.ApplicationContext) -> bool:
  """Return true if the author can command the bot.

  That is, if the bot is in the same channel as the author.
  """

  return (
    isinstance(ctx.author, discord.Member)
    and ctx.author.voice is not None
    and ctx.voice_client is not None
    and ctx.author.voice.channel == ctx.voice_client.channel
  )


def _bot_name(ctx: dctx.ApplicationContext) -> str:
  """Return either the concrete bot name if available, or a generic noun for it."""

  return "the bot" if ctx.bot.user is None else ctx.bot.user.name


def _track_name(playlist: Optional[playlists.Playlist]) -> str:
  """Return the quoted name of the current track of the given playlist, or else the word "track"."""

  return (
    f'"{playlist.current_track_name}"'
    if playlist is not None and playlist.current_track_name
    else "track"
  )


class ShiloGuild:
  """Represents the presence of ShiloBot in one guild.

  This allows for independent playback (e.g. position in playlists) per guild.
  """

  def __init__(self, playlist_config: dict[str, list[str]]):
    self._playlists: dict[str, playlists.Playlist] = {}
    for name, globs in playlist_config.items():
      self._playlists[name] = playlists.Playlist(name, sum([glob.glob(p) for p in globs], []))

    self._playlist: Optional[playlists.Playlist] = None

    self._next_callbacks: dict[str, utils.CancellableCoroutine] = {}

  async def Join(self, ctx: dctx.ApplicationContext, announce: bool = False) -> JoinResult:
    """Return true if bot successfully joined author's voice channel."""

    # Joining a voice channel seems to take a few seconds, so we defer our response to avoid
    # timeout errors.
    await ctx.defer()

    dest: Optional[discord.VoiceState] = (
      ctx.author.voice if isinstance(ctx.author, discord.Member) else None
    )

    # No channel to connect to.
    if not dest:
      await ctx.followup.send("You must connect to a voice channel!")
      return JoinResult.FAIL

    # Already connected to correct channel.
    if ctx.voice_client and ctx.voice_client.channel == dest.channel:
      if announce:
        await ctx.followup.send("Already connected!")
      return JoinResult.ALREADY_JOINED

    if ctx.voice_client:
      await self._Disconnect(ctx.voice_client)

    dest_channel: discord.VoiceChannel = cast(discord.VoiceChannel, dest.channel)
    await dest_channel.connect()

    # Deafen the bot to assure users they aren't being eavesdropped on.
    await ctx.guild.change_voice_state(channel=dest_channel, self_deaf=True)

    logging.info(f'Connected to voice channel "{dest_channel.name}".')
    await ctx.followup.send(f'Connected to the voice channel "{dest_channel.name}".')
    return JoinResult.SUCCESS

  async def Leave(self, ctx: dctx.ApplicationContext) -> None:
    """Leave the currently-connected channel."""

    await ctx.defer()

    if not _can_command(ctx):
      await ctx.followup.send(f"You must connect yourself to the same channel as {_bot_name(ctx)}!")
      return
    assert ctx.voice_client is not None

    channel_name = (
      f' "{ctx.voice_client.channel.name}"'
      if isinstance(ctx.voice_client.channel, discord.VoiceChannel)
      else ""
    )
    logging.info(f"Disconnected from voice channel{channel_name}.")

    await self._Disconnect(ctx.voice_client)

    await ctx.followup.send("Disconnected.")

  async def Start(
    self, ctx: dctx.ApplicationContext, playlist_name: Optional[str] = None, restart: bool = False
  ) -> None:
    """Start playing the current playlist (or the given playlist)."""

    join_result: JoinResult = await self.Join(ctx)
    if join_result == JoinResult.FAIL:
      return

    # We start a deferred message in `Join`. However, we only populate it with content if we
    # performed a join. In the case that we did, we should output our response in a new message.
    # In the case that we didn't, we should output our response as the original deferred message.
    def broadcast(msg):
      return ctx.followup.send(msg) if join_result == JoinResult.ALREADY_JOINED else ctx.send(msg)

    resolved_name: Optional[str] = (
      self._playlist.name if self._playlist and not playlist_name else playlist_name
    )
    if not resolved_name:
      logging.warning("Can't start: no playlist specified.")
      await broadcast("Playlist not specified!")
      return

    if resolved_name not in self._playlists:
      logging.warning(f'Playlist "{resolved_name}" doesn\'t exist.')
      await broadcast(f'Playlist "{resolved_name}" doesn\'t exist!')
      return
    playlist: playlists.Playlist = self._playlists[resolved_name]

    await broadcast(f'Playing playlist "{resolved_name}".')

    if restart:
      playlist.Restart()

    # Race: "next song" callback executes before we've started the new stream.
    if self._playlist:
      self._next_callbacks[self._playlist.name].Cancel()

    await self._PlayCurrent(ctx, playlist)

  async def Restart(
    self, ctx: dctx.ApplicationContext, playlist_name: Optional[str] = None
  ) -> None:
    """Restart the current (or a given) playlist."""

    await self.Start(ctx, playlist_name, True)

  async def Stop(self, ctx: dctx.ApplicationContext) -> None:
    """Stop the currently-playing playlist."""

    if not _can_command(ctx):
      await ctx.respond(f"You must connect yourself to the same channel as {_bot_name(ctx)}!")
      return
    assert ctx.voice_client is not None

    if not ctx.voice_client.is_playing():
      logging.warning("Tried to stop with nothing playing.")
      await ctx.respond("Nothing to stop!")
      return

    # Playing => active playlist.
    assert self._playlist is not None

    # Needed to stop the after-play callback from starting the next song.
    self._next_callbacks[self._playlist.name].Cancel()
    ctx.voice_client.stop()

    logging.info(f"Playback of {_track_name(self._playlist)} stopped.")
    await ctx.respond(f'Stopped playlist "{self._playlist.name}".')

  async def Next(self, ctx: dctx.ApplicationContext) -> None:
    """Move to the next track in the current playlist."""

    if not await self._ReportActivePlaylistControl(ctx):
      return
    assert self._playlist is not None and ctx.voice_client is not None

    logging.info("Skipping to next.")

    await ctx.respond(f"Finished {_track_name(self._playlist)}.")
    if ctx.voice_client.is_playing():
      # The after-play callback will automatically start playing the next song.
      ctx.voice_client.stop()
    else:
      self._playlist.Skip()
      await ctx.send(f"Loaded {_track_name(self._playlist)}.")

  async def FastForward(self, ctx: dctx.ApplicationContext, interval_str: str) -> None:
    """Fast-forward the current song."""

    if not await self._ReportActivePlaylistControl(ctx):
      return
    assert self._playlist is not None and ctx.voice_client is not None

    interval: Optional[datetime.timedelta] = utils.parse_interval(interval_str)
    if not interval:
      await ctx.respond(f'Couldn\'t understand interval "{interval_str}"!')
      logging.warning(f'Cannot fast-forward by bad interval "{interval_str}".')
      return

    self._playlist.FastForward(interval)

    logging.info(f"Fast-forwarding by {str(interval)}.")
    await ctx.respond(f"Fast-forwarded {_track_name(self._playlist)}.")

    if ctx.voice_client.is_playing():
      # Race: "next song" callback executes before we've started the new stream.
      self._next_callbacks[self._playlist.name].Cancel()

      await self._PlayCurrent(ctx, self._playlist, announce=False)

  async def List(self, ctx: dctx.ApplicationContext, playlist_name: Optional[str] = None) -> None:
    """List playlists or the tracks in an individual playlist."""

    # Print playlist list.
    if not playlist_name:
      playlist_names: list[str] = list(self._playlists.keys())
      current_index: int = playlist_names.index(self._playlist.name) if self._playlist else -1
      table: str = playlists.get_playlist_listing(playlist_names, current_index)
      await ctx.respond(f"```\n{table}\n```")
      return

    # Print specific playlist.
    if playlist_name not in self._playlists:
      logging.warning(f'Trying to print non-existent playlist "{playlist_name}".')
      await ctx.respond(f'No playlist "{playlist_name}"!')
      return

    await ctx.respond(f"```\n{self._playlists[playlist_name].GetTrackListing()}\n```")

  async def OnVoiceStateUpdate(
    self,
    bot_voice_client: discord.VoiceClient,
    before: discord.VoiceState,
    after: discord.VoiceState,
  ) -> None:
    """Leave the voice channel once everyone else has."""

    # TODO: find out how to annotate with a Connectable type.
    bot_channel = cast(discord.VoiceChannel, bot_voice_client.channel)

    # Nothing to do if:
    #   1) We aren't connected to a voice channel, or
    #   2) The user isn't leaving our channel.
    if not bot_channel or before.channel != bot_channel or after.channel == bot_channel:
      return

    # Only leave if there are no users left.
    if [m for m in bot_channel.members if not m.bot]:
      return

    logging.info(f'Disconnected from empty voice channel "{bot_channel.name}".')

    await self._Disconnect(bot_voice_client)

  async def _PlayCurrent(
    self, ctx: dctx.ApplicationContext, playlist: playlists.Playlist, announce: bool = True
  ) -> None:
    """Play the current entry from the given playlist over the bot voice channel.

    The bot must be connected to some voice channel.
    """

    assert ctx.voice_client is not None

    if not playlist.current_track_name:
      logging.warning(f'Tried to play empty playlist "{playlist.name}".')
      await ctx.send(f'Couldn\'t play empty playlist "{playlist.name}"!')
      return

    stream: Optional[playlists.ResumedAudio] = await playlist.MakeStream()
    if not stream:
      logging.error(f"Couldn't play {_track_name(playlist)}.")
      await ctx.send(f"Couldn't play {_track_name(playlist)}!")
      return

    ctx.voice_client.stop()

    callback: utils.CancellableCoroutine = utils.CancellableCoroutine(
      self._PlayNextTrack(ctx, playlist)
    )

    def schedule_next_track(
      exception: Optional[Exception],
      ctx: dctx.ApplicationContext = ctx,
      callback: utils.CancellableCoroutine = callback,
      playlist: playlists.Playlist = playlist,
    ) -> None:
      if not ctx.voice_client:
        callback.Cancel()
        return

      future: Optional[futures.Future] = None
      if playlist.StreamHasError():
        callback.Cancel()
        print_err = ctx.send(f"Error playing {_track_name(playlist)}. Stopping.")
        future = asyncio.run_coroutine_threadsafe(print_err, ctx.voice_client.loop)
      else:
        future = asyncio.run_coroutine_threadsafe(callback.Run(), ctx.voice_client.loop)

      future.result()

    ctx.voice_client.play(stream, after=schedule_next_track)

    # Update for /next, /skip etc.
    self._playlist = playlist
    self._next_callbacks[playlist.name] = callback

    logging.info("Playback started.")
    if announce:
      await ctx.send(f"Playing {_track_name(playlist)}.")

  async def _PlayNextTrack(
    self, ctx: dctx.ApplicationContext, playlist: playlists.Playlist
  ) -> None:
    """Play the next track of the given playlist."""

    playlist.Skip()
    await self._PlayCurrent(ctx, playlist)

  async def _Disconnect(self, voice_client: discord.VoiceClient) -> None:
    """Stop the currently playing song, de-select the current playlist and disconnect from the current voice channel."""

    if self._playlist:
      self._next_callbacks[self._playlist.name].Cancel()
    voice_client.stop()
    self._playlist = None

    await voice_client.disconnect()

  async def _ReportActivePlaylistControl(self, ctx: dctx.ApplicationContext) -> bool:
    """Return true if the current author can command the bot and there is an active playlist.

    If not, report so to the user.
    """

    if not _can_command(ctx):
      await ctx.respond(f"You must connect yourself to the same channel as {_bot_name(ctx)}!")
      return False

    if not self._playlist:
      logging.warning("Tried to skip or fast-forward with no playlist active.")
      await ctx.respond("No playlist selected!")
      return False

    return True
