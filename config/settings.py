import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")

LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_ORGANIZATION_ID = os.getenv("LINKEDIN_ORGANIZATION_ID", "")
LINKEDIN_ENABLED = bool(LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORGANIZATION_ID)

FAL_API_KEY = os.getenv("FAL_API_KEY", "")
IMAGES_ENABLED = bool(FAL_API_KEY)
VIDEO_ENABLED = bool(FAL_API_KEY)


AGENT_MODEL = "claude-opus-4-8"
# On Railway: set DB_PATH=/data/voxify.db (persistent volume mounted at /data)
# Locally: defaults to voxify-agent/voxify.db
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "voxify.db"))


def validate_config():
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        raise EnvironmentError(
            f"Faltan variables de entorno requeridas: {', '.join(missing)}\n"
            "Copia .env.example a .env y completa los valores."
        )
