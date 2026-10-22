#!/usr/bin/env python3
"""Forge Player 0.1: local-first YouTube Music history organizer.
Standard-library only. No account credentials. No external network requests.
"""
import argparse
import csv
import hashlib
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import zipfile

ROOT = Path(__file__).resolve().parent
DB_DEFAULT = ROOT / 'forge_player.sqlite3'
VIDEO_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
PREFIXES = ('Watched ', 'Listened to ', 'Played ')
CATEGORIES = ('ELECTRONIC', 'ROCK', 'HIPHOP', 'UNSORTED')

def connect(db_path):
    con = sqlite3.connect(str(db_path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    return con

def video_id_from_url(url):
    if not url:
        return None
    raw = str(url).strip()
    if VIDEO_RE.fullmatch(raw):
        return raw
    try:
        obj = urlparse(raw)
        host = (obj.hostname or '').lower()
        if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
            if obj.path == '/watch':
                ident = parse_qs(obj.query).get('v', [None])[0]
            elif obj.path.startswith('/shorts/') or obj.path.startswith('/embed/'):
                ident = obj.path.split('/')[2]
            else:
                ident = None
        elif host == 'youtu.be':
            ident = obj.path.strip('/').split('/')[0]
        else:
            return None
        return ident if ident and VIDEO_RE.fullmatch(ident) else None
    except (ValueError, IndexError):
        return None

def normalized_time(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec='seconds')
    except ValueError:
        pass
    # Google Takeout HTML varies with locale and timezone; these are best-effort formats.
    raw = re.sub(r'\s+(?:EDT|EST|PDT|PST|UTC|GMT)$', '', raw)
    for fmt in ('%b %d, %Y, %I:%M:%S %p', '%b %d, %Y, %I:%M %p',
                '%B %d, %Y, %I:%M:%S %p', '%b %d, %Y, %H:%M:%S',
                '%d %b %Y, %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat(timespec='seconds')
        except ValueError:
            continue
    return None

def clean_title(s):
    s = re.sub(r'\s+', ' ', (s or '').strip())
    for p in PREFIXES:
        if s.lower().startswith(p.lower()):
            return s[len(p):].strip()
    return s

def detect_music(record, artist):
    source = str(record.get('header') or '')
    title = str(record.get('title') or '')
    url = str(record.get('titleUrl') or '')
    products = record.get('products', [])
    product_str = ' '.join(str(p) for p in products) if isinstance(products, list) else str(products)
    if 'music' in source.lower() or 'music.youtube.com' in url or 'music' in product_str.lower() or title.lower().startswith('listened to '):
        return 'music'
    if artist.lower().endswith(' - topic'):
        return 'music'
    return 'review'  # Never claim arbitrary YouTube videos are songs.

def parse_history_record(row):
    url = row.get('titleUrl', '')
    ident = video_id_from_url(url)
    title = clean_title(row.get('title', ''))
    if not ident or not title or title.lower().startswith(('a video that has been removed', 'a video that is unavailable')):
        return None
    subtitles = row.get('subtitles') or []
    artist = ''
    if isinstance(subtitles, list) and subtitles and isinstance(subtitles[0], dict):
        artist = str(subtitles[0].get('name') or '').strip()
    elif isinstance(subtitles, str):
        artist = subtitles
    return {'video_id': ident, 'title': title, 'artist': artist,
            'time': normalized_time(row.get('time')),
            'source': str(row.get('header') or ''),
            'music_status': detect_music(row, artist)}

def iterate_json_array(stream):
    """Incrementally decode a top-level JSON array without loading entire history into RAM."""
    decoder = json.JSONDecoder()
    buf = ''
    pos = 0
    eof = False
    started = False
    while True:
        if pos > 100000:
            buf = buf[pos:]
            pos = 0
        while pos >= len(buf) and not eof:
            chunk = stream.read(256 * 1024)
            if chunk:
                buf += chunk
            else:
                eof = True
        while pos < len(buf) and buf[pos].isspace():
            pos += 1
        if pos >= len(buf):
            if eof:
                if not started:
                    raise ValueError('No JSON array found')
                raise ValueError('Unexpected end of history JSON')
            continue
        if not started:
            if buf[pos] != '[':
                raise ValueError('Expected a Takeout JSON list')
            started = True
            pos += 1
            continue
        if buf[pos] == ']':
            return
        if buf[pos] == ',':
            pos += 1
            continue
        try:
            obj, n = decoder.raw_decode(buf, pos)
            pos = n
            yield obj
        except json.JSONDecodeError:
            if eof:
                raise
            chunk = stream.read(256 * 1024)
            if chunk:
                buf += chunk
            else:
                eof = True

class HistoryHTML(HTMLParser):
    """Best-effort parser for legacy Takeout HTML content cells."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.cell = None
        self.out = []
    def handle_starttag(self, tag, attrs):
        att = dict(attrs)
        if tag == 'div' and self.depth:
            self.depth += 1
        elif tag == 'div' and 'content-cell' in att.get('class', '').split():
            self.cell = {'lines': [], 'url': '', 'channel': ''}
            self.depth = 1
        if self.cell is not None:
            if tag in ('br', 'div'):
                self.cell['lines'].append('\n')
            if tag == 'a':
                href = att.get('href', '')
                if not self.cell['url'] and video_id_from_url(href):
                    self.cell['url'] = href
    def handle_data(self, data):
        if self.cell is not None:
            self.cell['lines'].append(data)
    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1
            if self.depth == 0:
                lines = [re.sub(r'\s+', ' ', s).strip() for s in ''.join(self.cell['lines']).split('\n')]
                lines = [s for s in lines if s]
                if self.cell['url'] and lines:
                    item = {'titleUrl': self.cell['url'], 'title': lines[0],
                            'subtitles': [{'name': lines[1] if len(lines) > 2 else ''}],
                            'time': next((t for t in reversed(lines) if normalized_time(t)), ''),
                            'header': 'YouTube'}
                    self.out.append(item)
                self.cell = None

def write_history(con, records, import_id, origin):
    added = 0
    parsed = 0
    untimed = 0
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        r = parse_history_record(rec)
        if not r:
            continue
        parsed += 1
        old = con.execute('SELECT title, artist, music_status, source FROM tracks WHERE video_id=?', (r['video_id'],)).fetchone()
        if not old:
            con.execute('INSERT INTO tracks(video_id,title,artist,source,music_status) VALUES(?,?,?,?,?)',
                        (r['video_id'], r['title'], r['artist'], r['source'], r['music_status']))
        else:
            artist = r['artist'] if r['artist'] and not old['artist'] else old['artist']
            status = 'music' if r['music_status'] == 'music' and old['music_status'] == 'review' else old['music_status']
            con.execute('UPDATE tracks SET artist=?,music_status=?,source=CASE WHEN source="" THEN ? ELSE source END WHERE video_id=?',
                        (artist, status, r['source'], r['video_id']))
        # Missing timestamp: unique to import position. Counts lifetime only and cannot be placed in 90-day window.
        if r['time']:
            key = hashlib.sha256(f"{r['video_id']}|{r['time']}|{r['source']}".encode()).hexdigest()
        else:
            untimed += 1
            key = hashlib.sha256(f"{import_id}|{origin}|{idx}".encode()).hexdigest()
        cursor = con.execute('INSERT OR IGNORE INTO listens(event_key,video_id,played_at,origin,import_id) VALUES(?,?,?,?,?)',
                             (key, r['video_id'], r['time'], origin, import_id))
        added += cursor.rowcount
        if parsed % 2500 == 0:
            con.commit()
    con.commit()
    return added, untimed

def like_id_and_metadata(data):
    """Loose parser for known Takeout likes JSON/list shapes, without fabricating plays."""
    if isinstance(data, dict):
        for key in ('videoId', 'video_id', 'id'):
            v = data.get(key)
            if isinstance(v, str) and VIDEO_RE.fullmatch(v):
                title = data.get('title') or data.get('snippet', {}).get('title', '') if isinstance(data.get('snippet', {}), dict) else data.get('title', '')
                return v, str(title or '')
        for k in ('url', 'titleUrl', 'videoUrl'):
            ident = video_id_from_url(data.get(k))
            if ident:
                return ident, str(data.get('title') or '')
        cd = data.get('contentDetails', {})
        if isinstance(cd, dict) and VIDEO_RE.fullmatch(str(cd.get('videoId', ''))):
            return cd['videoId'], str(data.get('snippet', {}).get('title', '') if isinstance(data.get('snippet'), dict) else '')
    return None, ''

def iterate_likes(data):
    if isinstance(data, list):
        for item in data:
            yield from iterate_likes(item)
    elif isinstance(data, dict):
        vid, title = like_id_and_metadata(data)
        if vid:
            yield vid, title
        else:
            for key in ('items', 'videos', 'entries', 'likes', 'playlistItems'):
                if key in data:
                    yield from iterate_likes(data[key])

def write_likes(con, items):
    n = 0
    for ident, title in items:
        old = con.execute('SELECT video_id FROM tracks WHERE video_id=?', (ident,)).fetchone()
        if not old:
            con.execute('INSERT INTO tracks(video_id,title,music_status) VALUES(?,?,?)', (ident, title or f'Video {ident}', 'review'))
        n += con.execute('UPDATE tracks SET is_liked=1 WHERE video_id=? AND is_liked=0', (ident,)).rowcount
    con.commit()
    return n

def import_entry(con, basename, stream, import_id):
    b = basename.lower().replace('\\', '/')
    fname = b.split('/')[-1]
    if fname in ('watch-history.json', 'watch_history.json'):
        with io.TextIOWrapper(stream, encoding='utf-8-sig') as f:
            added, untimed = write_history(con, iterate_json_array(f), import_id, basename)
        return added, 0, f'{untimed} missing timestamps' if untimed else ''
    if fname in ('watch-history.html', 'watch_history.html'):
        # HTML is much less dependable than JSON, primarily due to locale-specific timestamps.
        p = HistoryHTML()
        with io.TextIOWrapper(stream, encoding='utf-8-sig', errors='replace') as f:
            for chunk in iter(lambda: f.read(128 * 1024), ''):
                p.feed(chunk)
        added, untimed = write_history(con, p.out, import_id, basename)
        return added, 0, f'HTML best-effort: {untimed} timestamps unparsed; prefer JSON'
    if fname == 'likes.json' and '/playlists/' in ('/' + b):
        with io.TextIOWrapper(stream, encoding='utf-8-sig') as f:
            liked = write_likes(con, iterate_likes(json.load(f)))
        return 0, liked, ''
    if fname in ('liked-videos.csv','likes.csv') and '/playlists/' in ('/' + b):
        with io.TextIOWrapper(stream, encoding='utf-8-sig') as f:
            csvreader = csv.DictReader(f)
            def items():
                for row in csvreader:
                    vid = next((video_id_from_url(v) for v in row.values() if video_id_from_url(v)), None)
                    if vid:
                        yield vid, row.get('Video Title') or row.get('Title') or ''
            return 0, write_likes(con, items()), ''
    return 0, 0, ''

def import_path(con, path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    history_added = likes_added = 0
    notes = []
    if path.is_dir():
        children = [p for p in path.rglob('*') if p.is_file() and p.name.lower() in ('watch-history.json', 'watch-history.html', 'likes.json', 'liked-videos.csv', 'likes.csv')]
        for p in children:
            h, l, note = import_path(con, p)
            history_added += h
            likes_added += l
            if note:
                notes.append(note)
        return history_added, likes_added, '; '.join(notes) if notes else f'Scanned {len(children)} files'
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [item.filename for item in z.infolist() if not item.is_dir() and item.filename.lower().split('/')[-1] in ('watch-history.json','watch-history.html','likes.json','liked-videos.csv','likes.csv')]
            for name in names:
                with z.open(name) as f:
                    ident = hashlib.sha256((str(path.resolve()) + name + str(path.stat().st_size)).encode()).hexdigest()
                    h, l, note = import_entry(con, name, f, ident)
                    history_added += h
                    likes_added += l
                    if note: notes.append(note)
                    con.execute('INSERT OR REPLACE INTO import_log(import_id,basename,events_added,likes_added,notices) VALUES(?,?,?,?,?)', (ident, name, h, l, note))
        con.commit()
        return history_added, likes_added, '; '.join(notes)
    ident = hashlib.sha256((str(path.resolve()) + str(path.stat().st_size)).encode()).hexdigest()
    with path.open('rb') as f:
        h, l, note = import_entry(con, path.name, f, ident)
    con.execute('INSERT OR REPLACE INTO import_log(import_id,basename,events_added,likes_added,notices) VALUES(?,?,?,?,?)', (ident, path.name, h, l, note))
    con.commit()
    return h, l, note

# Lifetime and rolling-90-day metrics are recorded-play counts, not watch duration.
TRACK_QUERY = '''
SELECT t.*, COALESCE(c.plays_all,0) AS plays_all, COALESCE(c.plays_90,0) AS plays_90,
       COALESCE(c.days_90,0) AS days_90, COALESCE(s.skips_all,0) AS skips_all,
       (CASE WHEN t.favorite_override IS NOT NULL THEN t.favorite_override
         WHEN t.is_liked=1 OR COALESCE(c.plays_90,0)>=5 OR COALESCE(c.plays_all,0)>=12 THEN 1
         ELSE 0 END) AS is_favorite
FROM tracks t LEFT JOIN (
 SELECT video_id,COUNT(*) AS plays_all,
  SUM(CASE WHEN played_at >= :since THEN 1 ELSE 0 END) AS plays_90,
  COUNT(DISTINCT CASE WHEN played_at >= :since THEN substr(played_at,1,10) ELSE NULL END) AS days_90
 FROM listens GROUP BY video_id
) c ON c.video_id=t.video_id
LEFT JOIN (SELECT video_id, COUNT(*) AS skips_all FROM skips GROUP BY video_id) s ON s.video_id=t.video_id
'''

def filter_sql(playlist):
    if playlist == 'FAVORITES': return ' music_status="music" AND is_favorite=1 '
    if playlist == 'EMOTIONAL': return ' music_status="music" AND is_emotional=1 '
    if playlist == 'REVIEW': return ' music_status="review" '
    if playlist == 'ALL': return ' 1=1 '
    if playlist in CATEGORIES:
        return ' music_status="music" AND category="' + playlist + '" '
    return ' music_status="music" '

def tracks_list(con, playlist='ALL', query='', sort='popular', offset=0, limit=100):
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec='seconds')
    clauses = [filter_sql(playlist)]
    params = {'since': since, 'offset': max(0,offset), 'limit': min(max(1,limit),500)}
    if query:
        clauses.append('(title LIKE :q OR artist LIKE :q OR video_id LIKE :q)')
        params['q'] = '%' + query[:160] + '%'
    where = ' AND '.join(clauses)
    order = {'popular': 'plays_90 DESC, plays_all DESC, title COLLATE NOCASE',
             'lifetime': 'plays_all DESC, title COLLATE NOCASE',
             'alpha': 'title COLLATE NOCASE ASC',
             'skipped': 'skips_all DESC, plays_90 DESC'} .get(sort, 'plays_90 DESC')
    sq = 'SELECT * FROM (' + TRACK_QUERY + ') WHERE ' + where
    total = con.execute('SELECT COUNT(*) FROM (' + sq + ')', params).fetchone()[0]
    rows = con.execute(sq + ' ORDER BY ' + order + ' LIMIT :limit OFFSET :offset', params).fetchall()
    return {'total': total, 'tracks': [dict(r) for r in rows]}

def summary(con):
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec='seconds')
    vals = dict(con.execute('SELECT COUNT(*) AS songs, COALESCE(SUM(is_liked),0) AS likes FROM tracks').fetchone())
    vals['total_events'] = con.execute('SELECT COUNT(*) FROM listens').fetchone()[0]
    vals['recent_events'] = con.execute('SELECT COUNT(*) FROM listens WHERE played_at>=?', (since,)).fetchone()[0]
    vals['music_tracks'] = con.execute('SELECT COUNT(*) FROM tracks WHERE music_status="music"').fetchone()[0]
    vals['review_tracks'] = con.execute('SELECT COUNT(*) FROM tracks WHERE music_status="review"').fetchone()[0]
    vals['timeless_events'] = con.execute('SELECT COUNT(*) FROM listens WHERE played_at IS NULL').fetchone()[0]
    vals['skips'] = con.execute('SELECT COUNT(*) FROM skips').fetchone()[0]
    vals['playlists'] = {p: tracks_list(con,p,limit=1)['total'] for p in ('ELECTRONIC','ROCK','HIPHOP','FAVORITES','EMOTIONAL','REVIEW')}
    vals['top_artists'] = [dict(x) for x in con.execute('''SELECT t.artist, COUNT(l.video_id) AS plays FROM tracks t
        JOIN listens l ON l.video_id=t.video_id WHERE t.music_status='music' AND l.played_at>=? AND t.artist!=''
        GROUP BY t.artist ORDER BY plays DESC LIMIT 8''',(since,))]
    vals['recent_days'] = [dict(x) for x in con.execute('''SELECT substr(played_at,1,10) AS day,COUNT(*) AS plays
        FROM listens WHERE played_at>=? AND played_at IS NOT NULL GROUP BY day ORDER BY day ASC''',(since,))]
    return vals

class App(BaseHTTPRequestHandler):
    db_path = DB_DEFAULT
    def _local_host(self):
        # Reject unexpected Host headers (helps mitigate DNS rebinding to localhost).
        host = self.headers.get('Host', '').lower()
        return host in ('127.0.0.1:8765', 'localhost:8765', '127.0.0.1', 'localhost') or (
            host.split(':', 1)[0] in ('127.0.0.1','localhost') and
            host.split(':', 1)[-1].isdigit())
    def _json(self, data, status=200):
        b = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if not self._local_host():
            self._json({'error':'localhost only'}, 403)
            return
        url = urlparse(self.path)
        if url.path in ('/', '/index.html'):
            b = (ROOT/'static'/'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data: https:; frame-src https://www.youtube.com https://www.youtube-nocookie.com")
            self.send_header('Content-Length',str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        con = connect(self.db_path)
        q = parse_qs(url.query)
        try:
            if url.path == '/api/summary':
                self._json(summary(con))
            elif url.path == '/api/tracks':
                self._json(tracks_list(con, q.get('playlist',['ALL'])[0], q.get('q',[''])[0], q.get('sort',['popular'])[0], int(q.get('offset',[0])[0]), int(q.get('limit',[100])[0])))
            elif url.path == '/api/queue':
                playlist = q.get('playlist',['FAVORITES'])[0]
                # Return entire eligible pool for a session, up to a generous local-only safety limit.
                if playlist not in ('FAVORITES','EMOTIONAL','ELECTRONIC','ROCK','HIPHOP','UNSORTED'):
                    self._json({'error':'invalid playlist'},400)
                else:
                    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec='seconds')
                    query = 'SELECT video_id,title,artist,plays_90,skips_all FROM (' + TRACK_QUERY + ') WHERE ' + filter_sql(playlist) + ' ORDER BY plays_90 DESC LIMIT 20000'
                    rows = [dict(x) for x in con.execute(query, {'since': since})]
                    self._json({'tracks': rows, 'count': len(rows), 'capped': len(rows)==20000})
            else:
                self._json({'error':'not found'},404)
        except (ValueError,sqlite3.Error) as exc:
            self._json({'error':str(exc)},400)
        finally:
            con.close()
    def do_POST(self):
        if not self._local_host():
            self._json({'error':'localhost only'}, 403)
            return
        url = urlparse(self.path)
        if url.path not in ('/api/update','/api/skip'):
            self._json({'error':'not found'},404)
            return
        try:
            n = int(self.headers.get('Content-Length','0'))
            if n <= 0 or n > 8192:
                self._json({'error':'invalid payload size'},400)
                return
            payload = json.loads(self.rfile.read(n))
            vid = payload.get('video_id')
            if not isinstance(vid,str) or not VIDEO_RE.fullmatch(vid):
                self._json({'error':'invalid video_id'},400)
                return
            con = connect(self.db_path)
            if not con.execute('SELECT 1 FROM tracks WHERE video_id=?',(vid,)).fetchone():
                self._json({'error':'track not found'},404)
                return
            if url.path == '/api/skip':
                con.execute('INSERT INTO skips(video_id) VALUES(?)',(vid,))
            else:
                allowed = {'category','music_status','favorite_override','is_emotional','is_liked','title','artist'}
                updates = {k:v for k,v in payload.items() if k in allowed}
                if not updates:
                    self._json({'error':'no changes'},400)
                    return
                if 'category' in updates and updates['category'] not in CATEGORIES:
                    raise ValueError('Invalid category')
                if 'music_status' in updates and updates['music_status'] not in ('music','review','not_music'):
                    raise ValueError('Invalid music status')
                if 'favorite_override' in updates and updates['favorite_override'] not in (0,1,None):
                    raise ValueError('Invalid favorite override')
                for key in ('is_emotional','is_liked'):
                    if key in updates and updates[key] not in (0,1):
                        raise ValueError(f'Invalid {key}')
                for key in ('title','artist'):
                    if key in updates:
                        if not isinstance(updates[key],str) or not updates[key].strip() or len(updates[key])>350:
                            raise ValueError(f'Invalid {key}')
                if 'category' in updates:
                    updates['category_source'] = 'manual'
                setters = ', '.join(f'{k}=?' for k in updates) + ', updated_at=CURRENT_TIMESTAMP'
                con.execute('UPDATE tracks SET '+setters+' WHERE video_id=?',tuple(updates.values())+(vid,))
            con.commit()
            con.close()
            self._json({'ok':True})
        except (ValueError,TypeError,json.JSONDecodeError,sqlite3.Error) as exc:
            self._json({'error':str(exc)},400)
    def log_message(self, format, *args):
        print('[FORGE]', format % args)

def main():
    p = argparse.ArgumentParser(description='Forge Player local database + UI')
    p.add_argument('--db', default=str(DB_DEFAULT), help='SQLite database path')
    sub = p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    ip = sub.add_parser('import', help='Import Takeout ZIP, JSON, HTML or extracted folder')
    ip.add_argument('paths', nargs='+')
    sv = sub.add_parser('serve', help='Launch local dashboard (localhost only)')
    sv.add_argument('--port',type=int,default=8765)
    sub.add_parser('stats')
    e = sub.add_parser('export',help='Export current playlist titles/URLs to local CSV')
    e.add_argument('--out',default=str(ROOT/'playlist_export.csv'))
    opts = p.parse_args()
    con = connect(opts.db)
    if opts.command == 'init':
        print(f'Initialized {opts.db}')
    elif opts.command == 'import':
        for path in opts.paths:
            n,l,notice = import_path(con,path)
            print(f'{path}: new plays={n}, new likes={l}. {notice}')
        print(f"Total: {summary(con)['songs']} videos indexed, {summary(con)['music_tracks']} high-confidence music videos.")
    elif opts.command == 'stats':
        print(json.dumps(summary(con),indent=2))
    elif opts.command == 'export':
        out = Path(opts.out)
        with out.open('w',newline='',encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['playlist','video_id','title','artist','url','plays_90','plays_all'])
            for genre in ('ELECTRONIC','ROCK','HIPHOP','FAVORITES','EMOTIONAL'):
                offset=0
                while True:
                    res = tracks_list(con,genre,offset=offset,limit=500)
                    for t in res['tracks']:
                        w.writerow([genre,t['video_id'],t['title'],t['artist'],f"https://www.youtube.com/watch?v={t['video_id']}",t['plays_90'],t['plays_all']])
                    offset += len(res['tracks'])
                    if offset>=res['total'] or not res['tracks']: break
        print(f'Exported {out}')
    elif opts.command == 'serve':
        if not (1024 <= opts.port <= 65535):
            raise SystemExit('Choose port 1024-65535')
        App.db_path = opts.db
        address = f'http://127.0.0.1:{opts.port}/'
        print('Forge Player available at '+address)
        print('Local-only. Press Ctrl+C to exit.')
        con.close()
        ThreadingHTTPServer(('127.0.0.1',opts.port),App).serve_forever()
        return
    con.close()

if __name__ == '__main__':
    main()
