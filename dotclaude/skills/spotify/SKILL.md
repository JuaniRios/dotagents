---
name: spotify
description: Create, edit, inspect, and delete Spotify playlists on the user's account via a local CLI. Use whenever the user asks to make a playlist, add or remove tracks, rename a playlist, see what's in a playlist, list their playlists, or otherwise manage their Spotify library.
allowed-tools: Bash(python3:*)
---

# Spotify playlist management

Wraps `spotify_agent.py` (stdlib-only Python 3, no dependencies), which talks
directly to the Spotify Web API using a cached refresh token.

```bash
SPOTIFY=~/.claude/skills/spotify/spotify_agent.py
python3 $SPOTIFY <command>
```

Credentials live outside this repo, in `~/.config/spotify-agent/`: `env` holds the
client id/secret, `token.json` the cached refresh token. Both are `chmod 600` and
must never be printed or committed.

## You are the recommender

Spotify removed `/recommendations` for new apps in November 2024, along with
`audio-features` and `audio-analysis`. There is no replacement and no waitlist.

So when the user asks for "a playlist for X", **you** choose the tracks from your
own music knowledge. Write them as `Artist - Title` lines and pipe them in. Never
go looking for a Spotify recommendations endpoint — it does not exist for this app.

## Commands

| Command | Effect |
|---|---|
| `auth` | One-time browser consent. Only re-run if scopes change. |
| `whoami` | Verify the cached token works. |
| `list` | All playlists: `id  count  visibility  name` |
| `show <playlist>` | Print the playlist's tracks in order. |
| `search "Artist - Title"` | Resolve one track to a URI. |
| `create <name> [--public] [--desc T]` | Create from track lines on stdin. |
| `add <playlist>` | Append track lines from stdin. |
| `remove <playlist>` | Remove track lines from stdin. |
| `details <playlist> [--name N] [--desc D] [--public\|--private]` | Rename / re-describe / change visibility. |
| `delete <playlist> --yes` | Remove the playlist from the library. Irreversible. |

`<playlist>` accepts a name, a 22-char id, a `spotify:playlist:ID` uri, or an
`open.spotify.com` URL. Track lines are `Artist - Title`, one per line on stdin.

## Creating a playlist

```bash
printf '%s\n' \
  'Brian Eno - An Ending (Ascent)' \
  'Stars of the Lid - Requiem for Dying Mothers' \
  'Grouper - Heavy Water' \
  | python3 $SPOTIFY create "deep focus" --desc "no vocals"
```

Default to **private** unless the user asks for public. The last line of output is
the playlist URL — always give it to the user.

## Always surface what did not resolve

Track resolution is fuzzy-matched against a similarity floor. Lines that do not
clear it are printed to stderr as `! not found: <line>` and **skipped**. This is
deliberate: Spotify's search always returns *something*, so an unguarded match
would silently substitute a wrong song.

If any line is reported not-found, tell the user which ones and offer to retry them
with corrected spelling. Never report a playlist as complete when tracks were dropped.

Also watch the `(asked: ...)` annotation — it means the match differed from what was
requested (usually a remaster or a featured artist, occasionally a genuine mismatch).

## Removing tracks

`remove` matches only against tracks **actually in the playlist**, never the global
catalog — a catalog match yields a URI that isn't present, and the API returns 200
while removing nothing. The command prints the true `before -> after` count; if that
delta disagrees with the number of URIs requested, it warns on stderr. Trust the delta.

## Hard rules

1. Never pass `--yes` to `delete` unless the user explicitly asked to delete that
   specific playlist. Deletion is irreversible from the API side.
2. Never print the contents of `~/.config/spotify-agent/env` or `token.json`. They
   hold the client secret and refresh token.
3. Default new playlists to private.
4. Always report not-found lines. Never silently drop tracks.
5. Prefer `show` over assuming a playlist's contents before editing it.

## Failure modes

- **`403` on any call** — a scope is missing. Re-run `auth`.
- **`no token; run auth first`** — the refresh token cache is gone. Re-run `auth`.
- **`401` / refresh fails** — the app owner's Spotify **Premium** lapsed. Since
  March 2026 a Development Mode app requires the owner to hold active Premium;
  without it the app stops working entirely.
- **`no playlist named X`** — run `list` and match on the printed id instead.
- **Search feels shallow** — the `limit` maximum was cut from 50 to 10 in
  February 2026. It resolves one known track at a time; that's expected.
- **Empty `show` output** — a response-shape regression. The Feb 2026 API renamed
  the playlist item wrapper's `track` field to `item` (and `track` is now a bool).
- **`list` count disagrees with `show`** — the `/me/playlists` aggregate total is
  eventually consistent and lags right after a write. `show` (which reads
  `/playlists/{id}/items`) is authoritative. Not a bug; wait and re-run `list`.

## Covers, remasters, and originals

Searching a famous city-pop track by its English title often surfaces a **cover**
rather than the original, because the original is catalogued under its Japanese
name. Two that bite:

- `Miki Matsubara - Stay With Me` -> a cover. The original is
  `Miki Matsubara - Mayonaka no Door~stay with me`.
- `Junko Ohashi - Telephone Number` -> a JiLL-Decoy association cover. The original
  is `Junko Ohashi - テレフォン・ナンバー`.

When adding classic city pop, check the `+` line for an unexpected extra artist —
that is the tell for a cover or a remix. Prefer the Japanese title.

Some artists are simply absent from Spotify (Tatsuro Yamashita withholds his
catalogue; only covers appear). Report these as unavailable rather than adding
a cover in their place.

## API notes for future maintainers

Verified empirically against the live Feb 2026 Web API. The three write endpoints
use three *different* body keys — getting this wrong fails quietly:

| Operation | Call | Body |
|---|---|---|
| create | `POST /me/playlists` | `{"name": ..., "public": ...}` |
| add | `POST /playlists/{id}/items` | `{"uris": ["spotify:track:.."]}` |
| remove | `DELETE /playlists/{id}/items` | `{"items": [{"uri": ".."}]}` |
| delete | `DELETE /playlists/{id}/followers` | — |

A wrong key returns `400 No uris provided`. A correct key naming a URI that is not
in the playlist returns `200` and removes nothing. The legacy `/tracks` paths are
deprecated. Object-shape renames: playlist `tracks` → `items`; item wrapper
`track` → `item`.
