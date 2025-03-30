# ShiloBot

A Discord bot that plays shuffled playlists from its host's local storage. Designed for painless use in online TTRPG play, and named after a [famed bard](https://www.dmsguild.com/product/190946/Shilo-the-Buff).

## Usage
ShiloBot accepts the following commands.
| Command     | Argument          | Description                                                                                                                            |
| ----------- | ------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `/join`     |                   | Joins the user's current voice channel.                                                                                                |
| `/leave`    |                   | Leaves the bot's current voice channel.                                                                                                |
| `/start`    | `[playlist name]` | Starts the given playlist where it left off, or the last-played playlist if none is given.                                             |
| `/restart`  | `[playlist name]` | Starts the given playlist again, or the last-played playlist if none is given.                                                         |
| `/stop`     |                   | Stops playback.                                                                                                                        |
| `/next`     |                   | Skips to the next track in the current playlist.                                                                                       |
| `/ff`       | `interval`        | Fast-forwards the current track by the given interval. The interval should be a string of similar form to `1s`, `2 min` or `3minutes`. |
| `/list`     | `[playlist name]` | Prints a track listing of the given                                                                                                    |
| `/help`     |                   | Prints out available commands.                                                                                                         |

## Installation
To use ShiloBot, you must create your own Discord bot account and run the bot from a host machine.

### Dependencies
ShiloBot has the following dependencies:
  - python3 (e.g. `apt install python3`)
  - [pycord](https://pycord.dev) (e.g. `pip3 install py-cord`)
  - [ffmpeg](https://ffmpeg.org/) (e.g. `apt install ffmpeg`)

### Creating a bot account
Follow the discord.py instructions for [creating a new bot account](https://discordpy.readthedocs.io/en/stable/discord.html). ShiloBot requires the bot permissions to `Send Messages`, `Connect` and `Speak`.

### Configuring
ShiloBot is configured via the `shilo.json` file in the project directory. The JSON object defined in the file has the `token` attribute which should be set to your bot's Discord token, and a `playlists` attribute specifying the details of each playlist.

The `playlists` object has one attribute per playlist. The name of the attribute is the name of the playlist as it will appear to users (e.g. in the output of the `!list` command). The value of the attribute is a list of glob strings whose matching files together are the contents of the playlist.

### Running
The bot can be launched with the command `python3 shilo.py`.

# Code structure
ShiloBot is decomposed into four modules:
  - `shilo.py`. The entry point of the script, which defines the Discord bot itself. The bot merely delegates commands to handlers for relevant guilds.
  - `guild.py`. The handler for ShiloBot's presence in a single guild. Executes the lion's share of the bot's behaviour.
  - `playlist.py`. Audio- and playlist-specific logic, including an abstract representation of a single playlist.
  - `util.py`. Utility behaviour, such as logging and table formatting.
