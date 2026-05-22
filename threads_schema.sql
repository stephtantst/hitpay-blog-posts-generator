-- Run this in Supabase SQL editor to create the Threads module tables.

CREATE TABLE threads_posts (
  id                    SERIAL PRIMARY KEY,
  content               TEXT NOT NULL,
  market                VARCHAR(10),
  status                VARCHAR(20) NOT NULL DEFAULT 'draft',
  scheduled_at          TIMESTAMPTZ,
  posted_at             TIMESTAMPTZ,
  post_url              VARCHAR(500),
  editor_email          VARCHAR(200),
  source_blog_post_id   INTEGER REFERENCES posts(id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE threads_audit_log (
  id          SERIAL PRIMARY KEY,
  post_id     INTEGER NOT NULL REFERENCES threads_posts(id) ON DELETE CASCADE,
  user_email  VARCHAR(200),
  action      VARCHAR(50) NOT NULL,
  details     JSONB,
  timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
