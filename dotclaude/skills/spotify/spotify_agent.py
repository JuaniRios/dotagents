#!/usr/bin/env python3
"""Spotify playlist agent. Stdlib only, no dependencies.

  auth                          one-time browser consent
  whoami                        verify the cached token
  list                          list your playlists
  show <playlist>               print a playlist's tracks
  search "<query>"              resolve one track to a URI
  create <name> [--public] [--desc T]   create from stdin track lines
  add <playlist>                append stdin track lines
  remove <playlist>             remove stdin track lines
  details <playlist> [--name N] [--desc D] [--public|--private]
  delete <playlist> --yes        remove the playlist from your library

<playlist> is a name, id, spotify:playlist:ID uri, or open.spotify.com URL.
Track lines are "Artist - Title", one per line on stdin.
Unresolved lines are reported and skipped, never silently dropped.

Endpoint shapes verified empirically against the Feb 2026 Web API:
  create  POST   /me/playlists
  add     POST   /playlists/{id}/items      body {"uris": ["spotify:track:.."]}
  remove  DELETE /playlists/{id}/items      body {"items":[{"uri": ".."}]}
  read    GET    /playlists/{id}/items
  delete  DELETE /playlists/{id}/followers
The /tracks paths are deprecated. Note the three write bodies use three different
keys (uris / items / tracks) -- the wrong key returns 400 "No uris provided", and
a valid key with a URI that is absent returns 200 while removing nothing.

Response-shape gotchas (Feb 2026 renames):
  playlist object:    `tracks` -> `items`  ({"total": N})
  playlist item wrap: `track`  -> `item`   (`track` is now a bool flag)
"""

import argparse
import base64
import difflib
import http.server
import json
import pathlib
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

CONFIG_DIR = pathlib.Path.home() / ".config" / "spotify-agent"
ENV_FILE = CONFIG_DIR / "env"
TOKEN_FILE = CONFIG_DIR / "token.json"
API = "https://api.spotify.com/v1"

SCOPES = " ".join(
    [
        "playlist-read-private",
        "playlist-read-collaborative",
        "playlist-modify-private",
        "playlist-modify-public",
    ]
)

WRITE_CHUNK = 100  # API caps add/remove at 100 objects per request
SEARCH_LIMIT = 10  # Feb 2026 reduced the search limit maximum from 50 to 10


# ---------- config & auth ----------


def load_env():
    if not ENV_FILE.exists():
        sys.exit(f"missing {ENV_FILE}")
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI"):
        if not env.get(k):
            sys.exit(f"{k} not set in {ENV_FILE}")
    return env


def basic_auth(env):
    raw = f"{env['SPOTIFY_CLIENT_ID']}:{env['SPOTIFY_CLIENT_SECRET']}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def post_form(url, data, headers):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"token endpoint {e.code}: {e.read().decode()[:400]}")


def save_token(tok):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    TOKEN_FILE.chmod(0o600)


def cmd_auth(env):
    redirect = env["SPOTIFY_REDIRECT_URI"]
    parsed = urllib.parse.urlparse(redirect)
    if parsed.hostname == "localhost":
        sys.exit("Spotify rejects 'localhost'; register http://127.0.0.1:PORT/... instead")
    state = secrets.token_urlsafe(16)
    box = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box.update({k: v[0] for k, v in q.items()})
            ok = "code" in box and box.get("state") == state
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Done. Close this tab." if ok else b"Auth failed.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {
            "client_id": env["SPOTIFY_CLIENT_ID"],
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": SCOPES,
            "state": state,
        }
    )
    print(f"Opening browser. If nothing happens, visit:\n{url}\n", file=sys.stderr)
    webbrowser.open(url)
    while "code" not in box and "error" not in box:
        threading.Event().wait(0.2)

    if "error" in box:
        sys.exit(f"authorization denied: {box['error']}")
    if box.get("state") != state:
        sys.exit("state mismatch; aborting")

    save_token(
        post_form(
            "https://accounts.spotify.com/api/token",
            {
                "grant_type": "authorization_code",
                "code": box["code"],
                "redirect_uri": redirect,
            },
            {
                "Authorization": basic_auth(env),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    )
    print("Authorized. Refresh token cached.", file=sys.stderr)


def access_token(env):
    if not TOKEN_FILE.exists():
        sys.exit("no token; run `spotify_agent.py auth` first")
    tok = json.loads(TOKEN_FILE.read_text())
    fresh = post_form(
        "https://accounts.spotify.com/api/token",
        {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        {"Authorization": basic_auth(env), "Content-Type": "application/x-www-form-urlencoded"},
    )
    fresh.setdefault("refresh_token", tok["refresh_token"])  # often omitted on refresh
    save_token(fresh)
    return fresh["access_token"]


# ---------- api ----------


def api(token, method, path_or_url, body=None, **params):
    url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        if e.code == 403:
            detail += "\n(403 often means a missing scope -- rerun `auth`)"
        sys.exit(f"{method} {url} -> {e.code}: {detail}")


def paginate(token, path, **params):
    """Follow `next` links so we never depend on a specific limit maximum."""
    page = api(token, "GET", path, **params)
    while page:
        for item in page.get("items", []):
            yield item
        nxt = page.get("next")
        page = api(token, "GET", nxt) if nxt else None


# ---------- resolution ----------

_ID = re.compile(r"^[A-Za-z0-9]{22}$")


def playlist_id(token, ref):
    ref = ref.strip()
    if _ID.match(ref):
        return ref
    if ref.startswith("spotify:playlist:"):
        return ref.split(":")[-1]
    if "open.spotify.com" in ref:
        m = re.search(r"/playlist/([A-Za-z0-9]{22})", ref)
        if m:
            return m.group(1)
    matches = [p for p in paginate(token, "/me/playlists") if p["name"].lower() == ref.lower()]
    if not matches:
        sys.exit(f"no playlist named {ref!r} (try `list`)")
    if len(matches) > 1:
        ids = "\n".join(f"  {p['id']}  {p['name']}" for p in matches)
        sys.exit(f"{len(matches)} playlists named {ref!r}; pass an id:\n{ids}")
    return matches[0]["id"]


MATCH_FLOOR = 0.6  # below this, Spotify's "closest" result is not the asked-for track
COVERAGE_FLOOR = 0.6  # a contained phrase must cover this much of the containing one


def _norm(s):
    """Tokenize on Unicode word chars, so CJK titles survive. An ASCII-only
    filter here erases Japanese titles entirely and scores them 0.0."""
    return re.sub(r"[\W_]+", " ", s.lower(), flags=re.UNICODE).split()


def _sim(asked, got):
    """Token-aware similarity in [0,1].

    Containment counts as a full match ("Weird Fishes" vs "Weird Fishes / Arpeggi"),
    but only when the shorter side covers most of the longer one -- otherwise a
    one-word title like "zzzz" would fully match any phrase containing it.
    """
    a, g = set(_norm(asked)), set(_norm(got))
    if not a or not g:
        return 0.0
    # Containment alone is not enough: "Nirvana" is contained in "Approaching
    # Nirvana", and "zzzz" in any phrase holding it. Demand real coverage.
    if a <= g or g <= a:
        if min(len(a), len(g)) / max(len(a), len(g)) >= COVERAGE_FLOOR:
            return 1.0
    return difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(g))).ratio()


def _title_variants(title):
    """Spotify titles carry baggage: combined A/B tracks ("Heavy Water/I'd Rather
    Be Sleeping") and version suffixes ("The Chain - 2004 Remaster"). Compare the
    asked title against each segment, not just the whole string."""
    seen = [title]
    seen.append(re.split(r"\s+-\s+", title)[0])  # drop "- 2004 Remaster"
    seen.extend(p.strip() for p in re.split(r"\s*/\s*", title))
    seen.extend(re.sub(r"\(.*?\)", "", t).strip() for t in list(seen))
    # drop "feat. X" / "ft X" tails, which otherwise sink token coverage
    seen.extend(re.split(r"\bfe?a?t\.?\b", t, flags=re.I)[0].strip() for t in list(seen))
    return [t for t in dict.fromkeys(seen) if t]


def _score(asked_artist, asked_title, track):
    got_artists = [a["name"] for a in track["artists"]]
    title_s = max(_sim(asked_title, v) for v in _title_variants(track["name"]))
    if asked_artist is None:
        return title_s
    artist_s = max(_sim(asked_artist, a) for a in got_artists)
    return min(title_s, artist_s)  # both must hold, so take the weaker


def resolve(token, line):
    """Resolve 'Artist - Title' to (uri, label), or None if no confident match.

    Spotify's search always returns *something*, so an unguarded first-hit pickup
    silently substitutes a wrong track. Score candidates and reject weak ones.
    """
    line = line.strip()
    if not line:
        return None

    if " - " in line:
        asked_artist, asked_title = (s.strip() for s in line.split(" - ", 1))
        queries = [f'track:"{asked_title}" artist:"{asked_artist}"', line]
    else:
        asked_artist, asked_title = None, line
        queries = [line]

    best = (0.0, None)
    for q in queries:
        items = (
            api(token, "GET", "/search", q=q, type="track", limit=SEARCH_LIMIT)
            .get("tracks", {})
            .get("items", [])
        )
        for t in items:
            s = _score(asked_artist, asked_title, t)
            if s > best[0]:
                best = (s, t)
        if best[0] >= 0.99:  # exact hit, no need to try the looser query
            break

    score, t = best
    if not t or score < MATCH_FLOOR:
        return None
    who = ", ".join(a["name"] for a in t["artists"])
    return t["uri"], f"{who} - {t['name']}"


def resolve_stdin(token):
    lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
    if not lines:
        sys.exit("no tracks on stdin")
    uris, resolved, missing = [], [], []
    for line in lines:
        hit = resolve(token, line)
        if hit:
            uris.append(hit[0])
            resolved.append((line, hit[1]))
        else:
            missing.append(line)
    return uris, resolved, missing


def report(resolved, missing, verb):
    for asked, got in resolved:
        note = "" if asked.lower() in got.lower() else f"   (asked: {asked})"
        print(f"  {verb} {got}{note}")
    for m in missing:
        print(f"  ! not found: {m}", file=sys.stderr)


def chunked_write(token, method, pid, uris):
    for i in range(0, len(uris), WRITE_CHUNK):
        batch = uris[i : i + WRITE_CHUNK]
        body = (
            {"uris": batch}
            if method == "POST"
            else {"items": [{"uri": u} for u in batch]}  # DELETE uses a different key
        )
        api(token, method, f"/playlists/{pid}/items", body)


# ---------- commands ----------


def cmd_list(token):
    for p in paginate(token, "/me/playlists"):
        vis = "public" if p.get("public") else "private"
        # Feb 2026 renamed the playlist object's `tracks` field to `items`.
        total = (p.get("items") or {}).get("total", "?")
        print(f"{p['id']}  {total:>4}  {vis:<7}  {p['name']}")


def cmd_show(token, ref):
    pid = playlist_id(token, ref)
    for i, entry in enumerate(paginate(token, f"/playlists/{pid}/items"), 1):
        # Feb 2026 renamed the wrapper's `track` object to `item`; `track` is now
        # a boolean flag on the object itself, so the old key silently yields None.
        t = entry.get("item") or {}
        if not t.get("name"):
            continue
        who = ", ".join(a["name"] for a in t.get("artists", []))
        print(f"{i:>3}. {who} - {t['name']}")


def cmd_create(token, args):
    uris, resolved, missing = resolve_stdin(token)
    if not uris:
        sys.exit("nothing resolved; refusing to create an empty playlist")
    pl = api(
        token,
        "POST",
        "/me/playlists",
        {"name": args.name, "public": args.public, "description": args.desc or ""},
    )
    chunked_write(token, "POST", pl["id"], uris)
    report(resolved, missing, "+")
    print(f"\n{len(uris)} added, {len(missing)} missing")
    print(pl["external_urls"]["spotify"])


def cmd_add(token, ref):
    pid = playlist_id(token, ref)
    uris, resolved, missing = resolve_stdin(token)
    if not uris:
        sys.exit("nothing resolved; nothing added")
    chunked_write(token, "POST", pid, uris)
    report(resolved, missing, "+")
    print(f"\n{len(uris)} added, {len(missing)} missing")


def playlist_entries(token, pid):
    """[(uri, artists, title)] for everything currently in the playlist."""
    out = []
    for entry in paginate(token, f"/playlists/{pid}/items"):
        t = entry.get("item") or {}
        if t.get("name") and t.get("uri"):
            out.append((t["uri"], [a["name"] for a in t.get("artists", [])], t["name"]))
    return out


def cmd_remove(token, ref):
    pid = playlist_id(token, ref)
    lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
    if not lines:
        sys.exit("no tracks on stdin")

    entries = playlist_entries(token, pid)
    if not entries:
        sys.exit("playlist is empty")

    # Match against what is actually IN the playlist. Resolving against the global
    # catalog can yield a URI that is not present, and the API returns 200 for a
    # no-op delete -- so a catalog match would report success while removing nothing.
    uris, resolved, missing = [], [], []
    for line in lines:
        if " - " in line:
            asked_artist, asked_title = (s.strip() for s in line.split(" - ", 1))
        else:
            asked_artist, asked_title = None, line.strip()

        best = (0.0, None)
        for uri, artists, title in entries:
            fake = {"name": title, "artists": [{"name": a} for a in artists]}
            s = _score(asked_artist, asked_title, fake)
            if s > best[0]:
                best = (s, (uri, artists, title))
        if best[0] >= MATCH_FLOOR and best[1]:
            uri, artists, title = best[1]
            if uri not in uris:
                uris.append(uri)
                resolved.append((line, f"{', '.join(artists)} - {title}"))
        else:
            missing.append(line)

    if not uris:
        report([], missing, "-")
        sys.exit("nothing in the playlist matched; nothing removed")

    before = api(token, "GET", f"/playlists/{pid}/items", limit=1)["total"]
    chunked_write(token, "DELETE", pid, uris)
    after = api(token, "GET", f"/playlists/{pid}/items", limit=1)["total"]

    report(resolved, missing, "-")
    print(f"\n{before - after} removed (playlist {before} -> {after}), {len(missing)} not matched")
    if before - after != len(uris):
        print(
            f"warning: asked to remove {len(uris)} uri(s) but count fell by {before - after}",
            file=sys.stderr,
        )


def cmd_delete(token, args):
    """'Deleting' a playlist is unfollowing it -- DELETE /playlists/{id}/followers.
    Irreversible from the API side, so require an explicit --yes."""
    pid = playlist_id(token, args.playlist)
    pl = api(token, "GET", f"/playlists/{pid}")
    if not args.yes:
        sys.exit(f"refusing to delete {pl['name']!r} ({pid}) without --yes")
    api(token, "DELETE", f"/playlists/{pid}/followers")
    print(f"deleted {pl['name']!r} ({pid})")


def cmd_details(token, args):
    pid = playlist_id(token, args.playlist)
    body = {}
    if args.name:
        body["name"] = args.name
    if args.desc is not None:
        body["description"] = args.desc
    if args.public:
        body["public"] = True
    if args.private:
        body["public"] = False
    if not body:
        sys.exit("nothing to change")
    api(token, "PUT", f"/playlists/{pid}", body)
    print(f"updated {pid}: {', '.join(body)}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    sub.add_parser("whoami")
    sub.add_parser("list")
    sub.add_parser("show").add_argument("playlist")
    sub.add_parser("search").add_argument("query")

    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--public", action="store_true")
    c.add_argument("--desc", default="")

    sub.add_parser("add").add_argument("playlist")
    sub.add_parser("remove").add_argument("playlist")

    d = sub.add_parser("details")
    d.add_argument("playlist")
    d.add_argument("--name")
    d.add_argument("--desc")
    d.add_argument("--public", action="store_true")
    d.add_argument("--private", action="store_true")

    rm = sub.add_parser("delete")
    rm.add_argument("playlist")
    rm.add_argument("--yes", action="store_true")

    args = p.parse_args()
    env = load_env()

    if args.cmd == "auth":
        return cmd_auth(env)

    token = access_token(env)
    if args.cmd == "whoami":
        me = api(token, "GET", "/me")
        print(f"{me['display_name']} ({me['id']})")
    elif args.cmd == "list":
        cmd_list(token)
    elif args.cmd == "show":
        cmd_show(token, args.playlist)
    elif args.cmd == "search":
        hit = resolve(token, args.query)
        print(f"{hit[1]}\n{hit[0]}" if hit else "no match")
    elif args.cmd == "create":
        cmd_create(token, args)
    elif args.cmd == "add":
        cmd_add(token, args.playlist)
    elif args.cmd == "remove":
        cmd_remove(token, args.playlist)
    elif args.cmd == "details":
        cmd_details(token, args)
    elif args.cmd == "delete":
        cmd_delete(token, args)


if __name__ == "__main__":
    main()
