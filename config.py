import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Groq
GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Rate limiting
RATE_LIMIT_GLOBAL: list[str] = ["200 per day", "10 per hour"]
RATE_LIMIT_SUBMIT: str = "10 per minute"
