# ShiloBot

A Discord bot that plays shuffled playlists from its host's local storage. Designed for painless use in online TTRPG play, and named after a [famed bard](https://www.dmsguild.com/product/190946/Shilo-the-Buff).

# Usage
ShiloBot accepts the following commands.
| Command     | Argument          | Description                                                                                                                            |
| ----------- | ------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `!join`     |                   | Joins the user's current voice channel.                                                                                                |
| `!leave`    |                   | Leaves the bot's current voice channel.                                                                                                |
| `!start`    | `[playlist name]` | Starts the given playlist where it left off, or the last-played playlist if none is given.                                             |
| `!restart`  | `[playlist name]` | Starts the given playlist again, or the last-played playlist if none is given.                                                         |
| `!stop`     |                   | Stops playback.                                                                                                                        |
| `!next`     |                   | Skips to the next track in the current playlist.                                                                                       |
| `!ff`       | `interval`        | Fast-forwards the current track by the given interval. The interval should be a string of similar form to `1s`, `2 min` or `3minutes`. |
| `!list`     | `[playlist name]` | Prints a track listing of the given                                                                                                    |
| `!help`     |                   | Prints out available commands.                                                                                                         |
