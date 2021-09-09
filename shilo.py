#!/usr/bin/python3

import json

import discord.ext.commands

import guild

CONFIG_FILE = 'shilo.json'

# Read config.

g_config = json.loads(open(CONFIG_FILE, 'r').read())

# Define bot.

g_bot = discord.ext.commands.Bot(command_prefix='!')
g_guild = guild.ShiloGuild(g_config['playlists'])


@g_bot.event
async def on_ready():
    print(f'[INFO] {g_bot.user.name} connected.')


@g_bot.command(name='join')
async def join(ctx):
    await g_guild.Join(ctx)


@g_bot.command(name='leave')
async def leave(ctx):
    await g_guild.Leave(ctx)


@g_bot.command(name='start')
async def start(ctx, playlist_name=None):
    await g_guild.Start(ctx, playlist_name)


@g_bot.command(name='restart')
async def restart(ctx, playlist_name=None):
    await g_guild.Restart(ctx, playlist_name)


@g_bot.command(name='stop')
async def stop(ctx):
    await g_guild.Stop(ctx)


@g_bot.command(name='next')
async def next(ctx):
    await g_guild.Next(ctx)


@g_bot.command(name='ff')
async def ff(ctx, interval_str):
    await g_guild.FastForward(ctx, interval_str)


@g_bot.command(name='list')
async def list(ctx, playlist_name=None):
    await g_guild.List(ctx, playlist_name)


# Run bot.

g_bot.run(g_config['token'])
