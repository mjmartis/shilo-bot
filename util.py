#!/usr/bin/python3

import datetime
import os

# Helper object holding a callback that can be cancelled.
class CancellableCoroutine():
    def __init__(self, callback):
        self._cancelled = False
        self._callback = callback

    def Cancel(self):
        self._cancelled = True
        self._callback.close()

    async def Run(self):
        if self._cancelled:
            return

        await self._callback

# Basic parsing of human-readable intervals like '1s', '10mins'.
def parse_interval(s):
    INTERVALS = {
        "s": datetime.timedelta(seconds=1),
        "sec": datetime.timedelta(seconds=1),
        "secs": datetime.timedelta(seconds=1),
        "seconds": datetime.timedelta(seconds=1),
        "m": datetime.timedelta(minutes=1),
        "min": datetime.timedelta(minutes=1),
        "mins": datetime.timedelta(minutes=1),
        "minutes": datetime.timedelta(minutes=1),
        "hr": datetime.timedelta(hours=1),
        "hrs": datetime.timedelta(hours=1),
        "hours": datetime.timedelta(hours=1),
    }

    try:
        suffix = s.lstrip('0123456789.')
        unit = suffix.strip().lower()
        num = float(s[:-len(suffix)].strip())

        return num * INTERVALS[unit]

    except:
        return None

# Returns the basename of the path without any extension.
def file_stem(path):
    basename = os.path.basename(path)
    return basename.split('.')[0]
