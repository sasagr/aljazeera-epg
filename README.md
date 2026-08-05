# aljazeera-epg

A cloud-hosted **XMLTV EPG for Al Jazeera English**.

Al Jazeera publishes no guide feed, and the third-party ones are unreliable. Its own schedule page
at <https://www.aljazeera.com/schedule> carries the next eight days —
[`generate.py`](generate.py) reads them and writes [`aljazeera.xml`](aljazeera.xml). A GitHub Action
re-runs it every 6 hours and commits the file, so any IPTV app can attach the guide with a plain
URL.

## Where the data comes from

Not from the visible HTML. Only the current day's tab is populated in the page as served — the other
six are filled in by JavaScript when you click them — so scraping the markup yields one day of
guide.

The whole week is in `window.__APOLLO_STATE__`, a base64-encoded JSON cache that includes a
`schedule` array of ~300 entries with a day, a start time, a duration, a title and a description.

**Times are GMT, and the data says so rather than the documentation.** Each entry carries
`startDate`, the Unix timestamp of its day's midnight, and every one lands exactly on 00:00 UTC — so
`startDate + showTimeslot` is an absolute instant with nothing inferred. `generate.py` re-checks
that on every run: if a `startDate` stops being a UTC midnight, or stops agreeing with its own day
name, the run **fails** instead of publishing a guide quietly shifted by hours.

The script also refuses to write the file if fewer than 48 programmes parse, so a site redesign
leaves the last good guide in place rather than replacing it with a stub.

## Deploy (once)

1. Public repo `aljazeera-epg` with: `generate.py`, `aljazeera.xml`,
   `.github/workflows/epg.yml`, `README.md`, `.gitignore`.
2. Actions tab → run **"Generate Al Jazeera EPG"** (also runs every 6 hours).
3. Live at `https://raw.githubusercontent.com/<your-username>/aljazeera-epg/main/aljazeera.xml`.

## Add it to the app (Movie4All)

Settings ▸ IPTV ▸ edit the **Al Jazeera English** channel:

| Field | Value |
|-------|-------|
| **EPG URL** | `https://raw.githubusercontent.com/<your-username>/aljazeera-epg/main/aljazeera.xml` |
| **EPG channel id / tvg-id** | `aljazeera.english` |

If your playlist already gives that channel a different tvg-id, change `CHANNEL_ID` at the top of
`generate.py` to match it instead — the id only has to be the same on both sides.

## Run it locally

```
python3 generate.py
```

No dependencies: stdlib only, same as `tgs-epg`.
