import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
HITPAY_MCP_URL = "https://hitpay-knowledge-mcp.vercel.app/api/mcp"
CLAUDE_MODEL = "claude-opus-4-6"
POSTS_DIR = "posts"
DB_PATH = "posts.db"

# Google OAuth — create credentials at console.cloud.google.com
# Authorized redirect URI must be set to: {BASE_URL}/auth/callback
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please-set-in-env")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ALLOWED_DOMAIN = "hit-pay.com"
