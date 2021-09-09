#!/usr/bin/python3

import json

import discord.ext.commands

import guild

CONFIG_FILE = 'shilo.json'


# The top-level bot. Responsible for creating independent presences in
# different guilds and forwarding them commands.
class ShiloBot(discord.ext.commands.Bot):

    def __init__(self, playlist_config):
        super().__init__(command_prefix='!')

        self._playlist_config = playlist_config
        self._guilds = {}

        self._RegisterOnReady()
        self._RegisterJoin()
        self._RegisterLeave()
        self._RegisterStart()
        self._RegisterStop()
        self._RegisterRestart()
        self._RegisterNext()
        self._RegisterFastForward()
        self._RegisterList()

    def _RegisterOnReady(self):

        @self.event
        async def on_ready():
            print(f'[INFO] {self.user.name} connected.')

    def _RegisterJoin(self):

        @self.command(name='join')
        async def join(ctx):
            await self._EnsureGuild(ctx.guild).Join(ctx)

    def _RegisterLeave(self):

        @self.command(name='leave')
        async def leave(ctx):
            await self._EnsureGuild(ctx.guild).Leave(ctx)

    def _RegisterStart(self):

        @self.command(name='start')
        async def start(ctx, playlist_name=None):
            await self._EnsureGuild(ctx.guild).Start(ctx, playlist_name)

    def _RegisterRestart(self):

        @self.command(name='restart')
        async def restart(ctx, playlist_name=None):
            await self._EnsureGuild(ctx.guild).Restart(ctx, playlist_name)

    def _RegisterStop(self):

        @self.command(name='stop')
        async def stop(ctx):
            await self._EnsureGuild(ctx.guild).Stop(ctx)

    def _RegisterNext(self):

        @self.command(name='next')
        async def next(ctx):
            await self._EnsureGuild(ctx.guild).Next(ctx)

    def _RegisterFastForward(self):

        @self.command(name='ff')
        async def ff(ctx, interval_str):
            await self._EnsureGuild(ctx.guild).FastForward(ctx, interval_str)

    def _RegisterList(self):

        @self.command(name='list')
        async def list(ctx, playlist_name=None):
            await self._EnsureGuild(ctx.guild).List(ctx, playlist_name)

    # Retrieve the object for the given guild, creating a new one if necessary.
    def _EnsureGuild(self, g):
        if g.id not in self._guilds:
            self._guilds[g.id] = guild.ShiloGuild(self._playlist_config)
            print(f'[INFO] Initialising for guild "{g.name}".')

        return self._guilds[g.id]


def main():
    config = json.loads(open(CONFIG_FILE, 'r').read())
    bot = ShiloBot(config['playlists'])

    print('[INFO] Connecting to Discord.')
    bot.run(config['token'])


if __name__ == '__main__':
    main()
