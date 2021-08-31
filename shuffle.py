#!/usr/bin/python3

import json
from discord.ext import commands

CONFIG_FILE = 'shuffle.json'

# Read config.

config = json.loads(open(CONFIG_FILE, 'r').read())

# Define bot.

bot = commands.Bot(command_prefix='!')

def on_other_channel(ctx):
    return ctx.author.voice and ctx.voice_client and \
           ctx.author.voice.channel != ctx.voice_client.channel

@bot.event
async def on_ready():
    print(f'[INFO] {bot.user.name} connected.')

@bot.command(name='start')
async def start(ctx):
    print(f'[INFO] Received start command')

    if on_other_channel(ctx):
        await ctx.send(f'{bot.user.name} connected to a different channel!')
        return

    dest = ctx.author.voice

    if not dest:
        await ctx.send('User not in voice channel!')
        return

    await dest.channel.connect()
    await ctx.send(f'Joined the voice channel {dest.channel.name}.')

async def test(ctx):
    await ctx.send('test response')

# Run bot.

bot.run(config['metadata']['token'])
