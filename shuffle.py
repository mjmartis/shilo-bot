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

@bot.command(name='test', help='')
async def test(ctx):
    await ctx.send('test response')

# Run bot.

bot.run(config['metadata']['token'])
