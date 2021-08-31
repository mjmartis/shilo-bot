#!/usr/bin/python3

import json
from discord.ext import commands

CONFIG_FILE = 'shuffle.json'

# Read config.

config = json.loads(open(CONFIG_FILE, 'r').read())

# Define bot.

bot = commands.Bot(command_prefix='!')

@bot.event
async def on_ready():
    print(f'{bot.user.name} connected to Discord!')

@bot.command(name='start')
async def start(ctx):
    dest = ctx.author.voice

    if not dest:
        await ctx.send('User not in voice channel!')
        return

    # Move bot if it is already playing.
    #if ctx.voice_client:
    #    await ctx.voice_state.voice.move_to(dest)
    #    return

    await dest.channel.connect()
    await ctx.send(f'Joined the voice channel {dest.channel.name}.')

@bot.command(name='test')
async def test(ctx):
    await ctx.send('test response')

# Run bot.

bot.run(config['metadata']['token'])
