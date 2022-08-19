#!/usr/bin/python3

import json

import discord
import discord.ext.commands as dcoms

import guilds
import utils

from typing import Any, cast, Iterator, Optional

CONFIG_FILE: str = 'shilo.json'

# Strings for the bot help message.
HELP_MESSAGE: str = 'I am a renowned bard, here to play shuffled music to suit your mood.'
HELP_TABLE: list[list[str]] = [
    ['!join', '', 'Joins the voice channel that you\'re currently in.'],
    ['', '', ''],
    ['!leave', '', 'Leaves the current voice channel.'],
    ['', '', ''],
    [
        '!start', '[playlist name]',
        'Starts the given playlist where it left off, ' +
        'or the last-played playlist if no playlist is given.'
    ],
    ['', '', ''],
    [
        '!restart', '[playlist name]', 'Starts the given playlist again, ' +
        'or the last-played playlist if no playlist is given.'
    ],
    ['', '', ''],
    ['!stop', '', 'Stops current playback.'],
    ['', '', ''],
    ['!next', '', 'Skips to the next track in the current playlist.'],
    ['', '', ''],
    [
        '!ff', 'interval',
        'Fast-forwards the current track by the interval given. ' +
        'The interval should be a string of similar form to "1s", "2 min" ' +
        'or "3minutes".'
    ],
    ['', '', ''],
    [
        '!list', '[playlist name]',
        'Prints a track listing of the given playlist, ' +
        'or the listing of all playlists if no playlist is given.'
    ],
    ['', '', ''],
    ['!help', '', 'Shows this message.'],
]
HELP_WIDTH: int = 40


# The top-level bot. Responsible for creating independent presences in
# different guilds and forwarding them commands.
class ShiloBot(dcoms.Bot):

    def __init__(self, playlist_config: dict[str, list[str]]):
        super().__init__(command_prefix='!',
                         help_command=None,
                         intents=discord.Intents(messages=True,
                                                 message_content=True,
                                                 guilds=True,
                                                 voice_states=True))

        self._playlist_config: dict[str, list[str]] = playlist_config
        self._guilds: dict[int, guilds.ShiloGuild] = {}

        self._RegisterOnReady()
        self._RegisterOnVoiceStateUpdate()
        self._RegisterJoin()
        self._RegisterLeave()
        self._RegisterStart()
        self._RegisterRestart()
        self._RegisterStop()
        self._RegisterNext()
        self._RegisterFastForward()
        self._RegisterList()
        self._RegisterHelp()
        self._RegisterOnCommandError()

    def _RegisterOnReady(self) -> None:

        @self.event
        async def on_ready():
            utils.log(utils.LogSeverity.INFO, f'{self.user.name} connected.')

    def _RegisterOnVoiceStateUpdate(self) -> None:

        @self.event
        async def on_voice_state_update(member: discord.Member,
                                        before: discord.VoiceState,
                                        after: discord.VoiceState) -> None:
            # Find the right guild to which to forward the message.
            if member.bot or not before.channel:
                return
            guild: discord.Guild = cast(discord.VoiceChannel,
                                        before.channel).guild

            # Get the bot's voice client for the right guild.
            vcs: Iterator[discord.VoiceClient] = (
                vc for vc in self.voice_clients if vc.guild == guild)

            bot_vc: Optional[discord.VoiceClient] = next(vcs, None)
            if not bot_vc:
                return

            await self._EnsureGuild(guild).OnVoiceStateUpdate(
                bot_vc, before, after)

    def _RegisterJoin(self) -> None:

        @self.command(name='join')
        async def join(ctx: dcoms.Context) -> None:
            await self._EnsureGuild(ctx.guild).Join(ctx)

    def _RegisterLeave(self) -> None:

        @self.command(name='leave')
        async def leave(ctx: dcoms.Context) -> None:
            await self._EnsureGuild(ctx.guild).Leave(ctx)

    def _RegisterStart(self) -> None:

        @self.command(name='start')
        async def start(ctx: dcoms.Context,
                        playlist_name: Optional[str] = None) -> None:
            await self._EnsureGuild(ctx.guild).Start(ctx, playlist_name)

    def _RegisterRestart(self) -> None:

        @self.command(name='restart')
        async def restart(ctx: dcoms.Context,
                          playlist_name: Optional[str] = None) -> None:
            await self._EnsureGuild(ctx.guild).Restart(ctx, playlist_name)

    def _RegisterStop(self) -> None:

        @self.command(name='stop')
        async def stop(ctx: dcoms.Context):
            await self._EnsureGuild(ctx.guild).Stop(ctx)

    def _RegisterNext(self) -> None:

        @self.command(name='next')
        async def next(ctx: dcoms.Context) -> None:
            await self._EnsureGuild(ctx.guild).Next(ctx)

    def _RegisterFastForward(self, *args) -> None:

        @self.command(name='ff')
        async def ff(ctx: dcoms.Context, *args) -> None:
            interval_str: str = ' '.join([str(a) for a in args])
            await self._EnsureGuild(ctx.guild).FastForward(ctx, interval_str)

    def _RegisterList(self) -> None:

        @self.command(name='list')
        async def list(ctx: dcoms.Context,
                       playlist_name: Optional[str] = None) -> None:
            await self._EnsureGuild(ctx.guild).List(ctx, playlist_name)

    def _RegisterHelp(self) -> None:

        @self.command(name='help')
        async def help(ctx: dcoms.Context) -> None:
            utils.log(utils.LogSeverity.INFO, 'Printing help.')
            await ctx.send(f'{HELP_MESSAGE}\n' +
                           f'```{utils.format_table(HELP_TABLE, HELP_WIDTH)}```'
                          )

    def _RegisterOnCommandError(self) -> None:

        @self.event
        async def on_command_error(ctx: dcoms.Context,
                                   error: dcoms.CommandError) -> None:
            # Benign error: unknown command.
            if isinstance(error, dcoms.CommandNotFound):
                await ctx.send(
                    f'Couldn\'t understand command "{ctx.invoked_with}"! ' +
                    'Use !help for instructions.')
                utils.log(utils.LogSeverity.WARNING,
                          f'Bad command "{ctx.invoked_with}" received.')
                return

            # Otherwise, an unexpected error while running a command.
            await ctx.send('Command failed! Internal error.')
            utils.log(utils.LogSeverity.ERROR, f'Internal error: "{error}".')

    # Retrieve the object for the given guild, creating a new one if necessary.
    def _EnsureGuild(self, g: discord.Guild) -> guilds.ShiloGuild:
        if g.id not in self._guilds:
            self._guilds[g.id] = guilds.ShiloGuild(self._playlist_config)
            utils.log(utils.LogSeverity.INFO,
                      f'Initialising for guild "{g.name}".')

        return self._guilds[g.id]


def main() -> None:
    config: dict[str, Any] = json.loads(open(CONFIG_FILE, 'r').read())
    bot: ShiloBot = ShiloBot(config['playlists'])

    utils.log(utils.LogSeverity.INFO, 'Connecting to Discord.')
    bot.run(config['token'])


if __name__ == '__main__':
    main()
