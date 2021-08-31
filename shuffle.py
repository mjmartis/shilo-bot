import json
from discord.ext import commands

CONFIG_FN = 'shuffle.json'
config = json.loads(open(CONFIG_FN, 'r').read())

print(config['metadata']['token'])
