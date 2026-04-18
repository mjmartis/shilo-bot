#!/usr/bin/python3

import datetime
import os
import textwrap

from typing import Any, Coroutine, Iterable, Optional


class CancellableCoroutine:
  """Helper object holding a callback that can be cancelled."""

  def __init__(self, callback: Coroutine[None, None, Any]):
    self._cancelled: bool = False
    self._callback: Coroutine[None, None, Any] = callback

  def Cancel(self):
    self._cancelled = True
    self._callback.close()

  async def Run(self):
    if self._cancelled:
      return

    await self._callback


def parse_interval(s: str) -> Optional[datetime.timedelta]:
  """Parse a basic human-readable interval like "1s", "10mins"."""

  INTERVALS: dict[str, datetime.timedelta] = {
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
    suffix: str = s.lstrip("0123456789.")
    unit: str = suffix.strip().lower()
    num: float = float(s[: -len(suffix)].strip())

    return num * INTERVALS[unit]

  except BaseException:
    return None


def file_stem(path: str) -> str:
  """Return the basename of the path without any extension."""

  basename: str = os.path.basename(path)
  return basename.split(".")[0]


def format_table(table: Iterable[Iterable[str]], wrap_width: int = 80) -> str:
  """Accept a row-major matrix of strings, and return the string of the matrix in tabular form.

  Columns are aligned and have width no longer than the specified wrap width.
  """

  # Dimensions are: row, col, lines in entry.
  wrapped_table: list[list[list[str]]] = []

  # First, wrap each entry and make sure all entries on a row have the same number of lines.
  for row in table:
    # Dimensions are: col, lines in entry.
    wrapped_row: list[list[str]] = []

    # Step 1: split each entry into a list of lines.
    for unwrapped_entry in row:
      wrapped_entry: list[str] = textwrap.wrap(
        unwrapped_entry, wrap_width, replace_whitespace=False
      ) or [""]

      # Manually ensure every new line is a separate entry in the list.
      wrapped_row.append(sum([l.split("\n") for l in wrapped_entry], []))

    # Step 2: pad each entry to be the same number of lines.
    max_lines: int = max(len(entry) for entry in wrapped_row)
    for unpadded_entry in wrapped_row:
      unpadded_entry.extend([""] * (max_lines - len(unpadded_entry)))

    wrapped_table.append(wrapped_row)

  # Dimensions are: col, row.
  padded_table_t: list[list[str]] = []

  # Next, pad every line of each column to be the same size.
  for col in list(zip(*wrapped_table)):  # Transposed.
    # Unwrap the entries so that a column contains each line.
    unwrapped_col: list[str] = sum(col, [])
    max_width: int = max(len(l) for l in unwrapped_col)

    padded_col: list[str] = []
    for entry in unwrapped_col:
      padded_col.append(entry + "".join([" "] * (max_width - len(entry))))

    padded_table_t.append(padded_col)

  # Join padded entries into row strings, then row strings into an output string.
  return "\n".join("\t".join(row) for row in zip(*padded_table_t))
