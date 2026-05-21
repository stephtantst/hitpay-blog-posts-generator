-- Run this in your Supabase SQL editor to create the X posts tables.

CREATE TABLE IF NOT EXISTS x_posts (
  id           SERIAL PRIMARY KEY,
  content      TEXT NOT NULL,
  market       VARCHAR(10),
  status       VARCHAR(20) NOT NULL DEFAULT 'draft',
  scheduled_at TIMESTAMPTZ,
  posted_at    TIMESTAMPTZ,
  post_url     VARCHAR(500),
  editor_email VARCHAR(200),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS x_audit_log (
  id         SERIAL PRIMARY KEY,
  post_id    INTEGER NOT NULL REFERENCES x_posts(id) ON DELETE CASCADE,
  user_email VARCHAR(200),
  action     VARCHAR(50) NOT NULL,
  details    JSONB,
  timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_x_posts_status    ON x_posts (status);
CREATE INDEX IF NOT EXISTS idx_x_audit_log_post  ON x_audit_log (post_id);

-- Repurpose feature additions (run once):
ALTER TABLE posts ADD COLUMN IF NOT EXISTS repurposed_content JSONB;
ALTER TABLE x_posts ADD COLUMN IF NOT EXISTS source_blog_post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL;
