#!/usr/bin/python3

import datetime
import os
import textwrap


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
        "second": datetime.timedelta(seconds=1),
        "seconds": datetime.timedelta(seconds=1),
        "m": datetime.timedelta(minutes=1),
        "min": datetime.timedelta(minutes=1),
        "mins": datetime.timedelta(minutes=1),
        "minute": datetime.timedelta(minutes=1),
        "minutes": datetime.timedelta(minutes=1),
        "hr": datetime.timedelta(hours=1),
        "hrs": datetime.timedelta(hours=1),
        "hour": datetime.timedelta(hours=1),
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


# Accepts a row-major matrix of strings, and returns the string of the matrix
# in tabular form. Columns are aligned and have width no longer than the
# specified wrap width.
def format_table(table, wrap_width=80):
    # First, wrap each entry and make sure all entries on a row have the same
    # number of lines.
    wrapped_table = []
    for row in table:
        wrapped_row = []

        # Step 1: split each entry into a list of lines.
        for entry in row:
            wrapped_entry = textwrap.wrap(entry,
                                          wrap_width,
                                          replace_whitespace=False,
                                          drop_whitespace=False)

            # Manually ensure every new line is a separate entry in the list.
            wrapped_entries = sum([l.split('\n') for l in wrapped_entry], [])

            # Remove possible leading whitespace after '\n'.
            wrapped_row.append([e.lstrip() for e in wrapped_entries])

        # Step 2: pad each entry to be the same number of lines.
        max_lines = max(len(entry) for entry in wrapped_row)
        for entry in wrapped_row:
            entry.extend([''] * (max_lines - len(entry)))

        wrapped_table.append(wrapped_row)

    # Next, pad every line of each column to be the same size.
    padded_table_t = []
    for col in list(zip(*wrapped_table)):  # Transposed.
        # Unwrap the entries so that a column contains each line.
        unwrapped_col = sum(col, [])
        max_width = max(len(l) for l in unwrapped_col)

        padded_col = []
        for entry in unwrapped_col:
            padded_col.append(entry + ''.join([' '] * (max_width - len(entry))))

        padded_table_t.append(padded_col)

    # Join padded entries into row strings, then row strings into an output string.
    return '\n'.join(' '.join(row) for row in zip(*padded_table_t))
