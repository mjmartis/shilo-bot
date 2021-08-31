#!/usr/bin/python3

import discord
import discord.ext.commands
import glob
import json
import os
import random
#from discord import FFmpegOpusAudio
#from discord.ext import commands
#from random import shuffle

CONFIG_FILE = 'shuffle.json'

def file_stem(path):
    basename = os.path.basename(path)
    return basename.split('.')[0]

# Maintains a cursor in a list of music files and exposes an audio stream for
# the current file.
class Playlist:
    def __init__(self, name, fs):
        # Make copy.
        self.name = name
        self.fs = list(fs)

        # Populated in Restart.
        self.index = None
        self.cur_src = None

        # Start shuffled.
        self.Restart()

    # Clear current song and reshuffle playlist.
    def Restart(self):
        print(f'[INFO] Restarting playlist "{self.name}".')

        if self.cur_src:
            self.cur_src.clean_up()
        self.cur_src = None

        random.shuffle(self.fs)
        self.index = 0

    # Return the current audio source, or load it if it isn't initialised.
    async def CurrentStream(self):
        if self.index >= len(self.fs):
            return None

        if not self.cur_src:
            print(f'[INFO] Starting "{file_stem(self.fs[self.index])}".')
            self.cur_src = await discord.FFmpegOpusAudio.from_probe(self.fs[self.index])
        else:
            print(f'[INFO] Resuming "{file_stem(self.fs[self.index])}".')

        return self.cur_src

    # Move to the next song, reshuffling and starting again if there isn't one.
    def Next():
        self.index += 1

        if self.index >= len(self.fs):
            self.Restart()
            return

        if self.cur_src:
            self.cur_src.clean_up()
        self.cur_src = None

    def CurrentIndex(self):
        print(self.fs[self.index])
        return self.index

# Read config.

config = json.loads(open(CONFIG_FILE, 'r').read())

playlists = {}
for name, globs in config['playlists'].items():
    playlists[name] = Playlist(name, sum([glob.glob(p) for p in globs], []))

# Define bot.

bot = discord.ext.commands.Bot(command_prefix='!')

# Returns true if the author can command the bot. That is, if the bot is in the
# same channel as the author.
def can_command(ctx):
    return ctx.author.voice and (not ctx.voice_client or
           ctx.author.voice.channel == ctx.voice_client.channel)

@bot.event
async def on_ready():
    print(f'[INFO] {bot.user.name} connected.')

@bot.command(name='start')
async def start(ctx):
    print(f'[INFO] Joining voice channel.')

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {bot.user.name}!')
        return

    dest = ctx.author.voice

    if not dest:
        await ctx.send('User not in voice channel!')
        return

    await dest.channel.connect()
    await ctx.send(f'Joined the voice channel {dest.channel.name}.')

@bot.command(name='play')
async def play(ctx):
    print(f'[INFO] Playback started.')

    if not can_command(ctx):
        await ctx.send(f'You must connect yourself to the same channel as {bot.user.name}!')
        return

    ctx.voice_client.play(await playlists['p1'].CurrentStream())

# Run bot.

bot.run(config['token'])
