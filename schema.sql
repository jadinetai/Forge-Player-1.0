PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS tracks (
  video_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  artist TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  music_status TEXT NOT NULL DEFAULT 'review' CHECK (music_status IN ('music','review','not_music')),
  category TEXT NOT NULL DEFAULT 'UNSORTED' CHECK (category IN ('ELECTRONIC','ROCK','HIPHOP','UNSORTED')),
  category_source TEXT NOT NULL DEFAULT 'unclassified',
  is_liked INTEGER NOT NULL DEFAULT 0,
  favorite_override INTEGER CHECK(favorite_override IS NULL OR favorite_override IN (0,1)),
  is_emotional INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS listens (
  event_key TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES tracks(video_id),
  played_at TEXT,
  origin TEXT NOT NULL,
  import_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listens_video_time ON listens(video_id, played_at);
CREATE INDEX IF NOT EXISTS idx_listens_time ON listens(played_at);
CREATE TABLE IF NOT EXISTS skips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL REFERENCES tracks(video_id),
  skipped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reason TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS import_log (
  import_id TEXT PRIMARY KEY,
  basename TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  events_added INTEGER NOT NULL,
  likes_added INTEGER NOT NULL,
  notices TEXT NOT NULL DEFAULT ''
);
