import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
HITPAY_MCP_URL = "https://hitpay-knowledge-mcp.vercel.app/api/mcp"
CLAUDE_MODEL = "claude-opus-4-6"

# Supabase PostgreSQL connection string
DATABASE_URL = os.getenv("DATABASE_URL")

# Storage paths for markdown post files
_on_vercel = bool(os.getenv("VERCEL"))
_railway_volume = os.path.isdir("/data")

if _railway_volume:
    POSTS_DIR = "/data/posts"
elif _on_vercel:
    POSTS_DIR = "/tmp/posts"
else:
    POSTS_DIR = "posts"

# Google OAuth — create credentials at console.cloud.google.com
# Authorized redirect URI must be set to: {BASE_URL}/auth/callback
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please-set-in-env")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").strip().rstrip("/")
ALLOWED_DOMAIN = "hit-pay.com"
