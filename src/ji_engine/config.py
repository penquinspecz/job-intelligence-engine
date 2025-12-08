import os
from dotenv import load_dotenv

# Load .env file into environment
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Later we'll add more config, like storage paths, etc.
