#!/usr/bin/env python3
"""Generate an XMLTV EPG for Al Jazeera English from https://www.aljazeera.com/schedule .

Al Jazeera publishes no EPG feed, but its schedule page ships the whole week as data rather than
just as markup: `window.__APOLLO_STATE__` is base64-encoded JSON, and one record in it holds a
`schedule` array of 300-odd entries — eight days, each with a day name, a start time, a duration, a
title and a description.

That array is what this reads. The visible HTML was the obvious target and is the wrong one: only
the current day's tab is populated, the other six are filled in by JavaScript on click, so scraping
the page as served yields exactly one day of guide.

**Times are GMT, and the data proves it rather than the documentation claiming it.** Each entry
carries `startDate`, the Unix timestamp of ITS DAY's midnight — the same value for every programme
in a day — and every one of those lands exactly on 00:00 UTC. So `startDate + showTimeslot` is an
absolute instant, with nothing inferred. `sanity_check` re-establishes this on every run: if a
`startDate` ever stops being a UTC midnight, or stops agreeing with its own day name, the run fails
rather than quietly publishing a guide shifted by hours.

Stdlib only — runs on a stock GitHub Actions runner. Mirrors tgs-epg/generate.py.
"""

import base64
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

CHANNEL_ID = "aljazeera.english"          # paste this exact string as the app's tvg-id
CHANNEL_NAME = "Al Jazeera English"
CHANNEL_LOGO = "https://www.aljazeera.com/images/logo_aje.png"
URL = "https://www.aljazeera.com/schedule"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
OUT = "aljazeera.xml"
UTC = timezone.utc

_APOLLO = re.compile(r'window\.__APOLLO_STATE__\s*=\s*"([A-Za-z0-9+/=]+)"')
_TIMESLOT = re.compile(r'^\s*([0-2]?\d):([0-5]\d)\s*$')

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fetch() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def schedule_entries(page: str) -> list:
    """The raw `schedule` array out of the page's Apollo cache."""
    m = _APOLLO.search(page)
    if not m:
        raise SystemExit("! no __APOLLO_STATE__ in the page — the site has changed")
    state = json.loads(base64.b64decode(m.group(1)).decode("utf-8", "ignore"))
    # Found by shape, not by key: the record id (`Post:568783`) is a CMS row number and would be a
    # silly thing to hardcode.
    for value in state.values():
        if isinstance(value, dict) and isinstance(value.get("schedule"), list) and value["schedule"]:
            return value["schedule"]
    raise SystemExit("! no schedule array in __APOLLO_STATE__ — the site has changed")


def parse_duration(text: str) -> timedelta:
    """'01:00:0' → one hour. Malformed or zero falls back to 30 minutes, the grid's smallest slot."""
    parts = (text or "").split(":")
    try:
        hours, minutes, seconds = (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return timedelta(minutes=30)
    total = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return total if total > timedelta(0) else timedelta(minutes=30)


def sanity_check(entries: list) -> None:
    """Fail the run if the GMT assumption stops holding.

    Two independent tests, because the cost of being wrong here is a guide that looks perfectly
    healthy and is several hours out: every `startDate` must be a UTC midnight, and the weekday that
    timestamp falls on must be the one the entry names.
    """
    for entry in entries:
        stamp = int(entry["startDate"])
        if stamp % 86400 != 0:
            raise SystemExit(f"! startDate {stamp} is not a UTC midnight — times are no longer GMT")
        day = datetime.fromtimestamp(stamp, UTC)
        named = (entry.get("showDay") or "").strip().title()
        if named and named != DAY_NAMES[day.weekday()]:
            raise SystemExit(f"! {stamp} is a {DAY_NAMES[day.weekday()]} but the entry says {named} "
                             f"— the day grid no longer lines up with GMT")


def parse(entries: list) -> list:
    """[(start, stop, title, description)], in time order, one entry per slot."""
    out = {}
    for entry in entries:
        slot = _TIMESLOT.match(entry.get("showTimeslot") or "")
        title = (entry.get("showName") or "").strip()
        if not slot or not title:
            continue
        midnight = datetime.fromtimestamp(int(entry["startDate"]), UTC)
        start = midnight + timedelta(hours=int(slot.group(1)), minutes=int(slot.group(2)))
        # Keyed on the start: the page carries eight days and repeats a weekday at each end, so the
        # same slot can legitimately appear twice within one fetch.
        out[start] = (start, start + parse_duration(entry.get("duration")),
                      title, (entry.get("showDescription") or "").strip())
    return [out[k] for k in sorted(out)]


def xmltv_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S %z")


def main() -> int:
    print(f"Fetching {URL} …")
    try:
        page = fetch()
    except Exception as e:
        print(f"! fetch failed: {e}", file=sys.stderr)
        return 1

    entries = schedule_entries(page)
    sanity_check(entries)
    print(f"  {len(entries)} entries, all startDates are UTC midnights matching their day names")

    items = parse(entries)
    if len(items) < 48:
        # A week of a news channel is 250-plus programmes. Anything this small means the shape moved,
        # and overwriting a good guide with a stub is worse than failing the run.
        print(f"! only {len(items)} programmes parsed — refusing to write {OUT}", file=sys.stderr)
        return 1

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<tv generator-info-name="aljazeera-epg">',
             f'  <channel id="{CHANNEL_ID}">',
             f'    <display-name>{escape(CHANNEL_NAME)}</display-name>',
             f'    <icon src="{escape(CHANNEL_LOGO)}" />',
             '  </channel>']

    for start, stop, title, desc in items:
        lines.append(f'  <programme start="{xmltv_ts(start)}" stop="{xmltv_ts(stop)}" channel="{CHANNEL_ID}">')
        lines.append(f'    <title lang="en">{escape(title)}</title>')
        if desc:
            lines.append(f'    <desc lang="en">{escape(desc)}</desc>')
        lines.append('  </programme>')
    lines.append('</tv>')

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {OUT}: {len(items)} programmes, "
          f"{items[0][0]:%Y-%m-%d %H:%M} → {items[-1][1]:%Y-%m-%d %H:%M} GMT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
