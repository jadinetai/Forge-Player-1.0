# FORGE PLAYER v0.1

An experimental, local-first database and lightweight web interface for categorizing YouTube and YouTube Music listening history. Source code is Python 3 (standard library), SQLite, HTML, CSS and JavaScript. No dependencies, Google credentials, server hosting, telemetry, or video downloads.

## Quick start (Windows)

Unzip this project to a folder. Install Python 3 if needed. On Windows, double-click `START_FORGE_PLAYER.bat` to launch the local server and open the default browser (Opera if configured as your default). Alternatively, in that folder open PowerShell:

```powershell
py forge.py init
py forge.py serve
```

Open http://127.0.0.1:8765/ in Opera or Chrome. The library is empty until data is imported. Stop the server with Ctrl+C.

## Import an export from Google Takeout

When Takeout finishes, locate its ZIP parts. You do **not** need to upload your full ten-year account archive into a chat, unpack every part, or expose unrelated account data. Forge only reads a limited set of files from the archive. Google Takeout is not automatically polled.

```powershell
# Example: one ZIP part
py forge.py import "C:\Users\YOUR_NAME\Downloads\takeout-001.zip"

# Example: several 4GB ZIP parts (give their actual file paths)
py forge.py import "C:\Users\YOUR_NAME\Downloads\takeout-001.zip" "C:\Users\YOUR_NAME\Downloads\takeout-002.zip"

# Example: a JSON file or extracted folder
py forge.py import "C:\Users\YOUR_NAME\Downloads\Takeout\YouTube and YouTube Music"

py forge.py serve
```

The Takeout History format should preferably be **JSON**. Choosing 4 GB ZIP *parts* determines the archive split size, not a lossless-versus-lossy tradeoff: ZIP compression itself does not discard history records. This program recognizes `watch-history.json` and has a best-effort fallback for `watch-history.html`. It also recognizes legacy `playlists/likes.json` and possible `playlists/liked-videos.csv` and `playlists/likes.csv`. Liked videos may be absent from the export and may later require the official YouTube Data API with OAuth.

**Important**: YouTube Music and ordinary YouTube activity can be mixed in watch history. Forge auto-classifies YouTube Music entries and `- Topic` channels as **music**. Ordinary YouTube activity goes into **Review**. It will never assume all YouTube watch activity consists of songs. Specific genre labels are user-editable and initially **Unsorted**. More precise genre enrichment is a future feature. Liked videos not otherwise identified as music also remain in Review.

## What's included

- SQLite schema with indexed `tracks`, `listens`, `skips`, and import log tables.
- Rolling 90-day play counts, lifetime play counts, and top artists from timestamped plays.
- Five dynamic playlists: Electronic, Rock, Hip-Hop, Favorites, and manually curated Emotional.
- Editable genre, music status, favorite override, and emotional selection via local UI.
- Favorites automatically include confirmed songs that are liked, played at least 5 times in the past 90 days, or played at least 12 times in retained history. A manual favorite override can include or exclude a song.
- Player tab uses YouTube's official iframe embed (only if the video allows embedding), session shuffle without repeat until the pool exhausts, and explicit skip logging. Playback completion / automatic next is not yet wired up.
- Playlist export to CSV: `py forge.py export` (CSV is **not** a YouTube playlist upload).
- No OAuth yet, no direct playback control of external Opera or Chrome tabs, no extension yet, and no YouTube account modification yet.

## Accuracy and privacy notes

- A recorded "play" means a Takeout start event. It does not establish completed playback or listening duration.
- HTML dates may not parse reliably in non-US locales and are interpreted as UTC by the fallback parser. For accurate 90-day statistics use JSON.
- Timestamp-less imported events are counted in lifetime totals only.
- A video ID is a YouTube video, not an abstract musical recording. Alternate uploads are not yet deduplicated into one composition.
- Duplicate timestamp+video+source records are deduplicated across repeated imports. Very rare legitimate same-second replays may be merged.
- The database persists as `forge_player.sqlite3` in the project directory. This file may contain sensitive listening history. Do not commit it to GitHub or send it to strangers. A `.gitignore` is included.
- The dashboard binds to `127.0.0.1` only, not the network. It makes YouTube requests only if you initiate an embedded video.
- All previews and future player features must comply with YouTube's playback and API policies. v0.1 does not download or extract audio/video streams.

## Database commands

```powershell
py forge.py stats
py forge.py export --out "C:\Users\YOUR_NAME\Desktop\my-forge-playlists.csv"
py -m unittest discover -s tests -v
```

## Development roadmap

1. **v0.1:** Real Takeout import, schema, curating interface, local playlists, statistics. (This release.)
2. **v0.2:** Robust music metadata and genre enrichment, dedupe alternate song uploads, artist mapping, better CSV/Takeout compatibility.
3. **v0.3:** Optional YouTube OAuth2 sync for likes and playlists, explicit user authorization and quota-aware resumable publishing.
4. **v0.4:** Official YouTube IFrame API events for automatic next and improved play controls, queue persistence, skip thresholds with reversible exclusions.
5. **v1:** Browser extension or desktop integration with user-authorized Chrome/Opera session, optional open-on-YouTube behavior, import sync, public GitHub release.

## References

- Google Takeout structure: https://github.com/google/takeout
- YouTube Data API: https://developers.google.com/youtube/v3/docs
- YouTube IFrame Player API: https://developers.google.com/youtube/iframe_api_reference
