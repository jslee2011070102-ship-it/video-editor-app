import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / '.env')

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

# AI provider: 'gemini' or 'claude'
# Gemini 기본값. Claude로 교체하려면 .env에서 AI_PROVIDER=claude 로 설정
AI_PROVIDER = os.getenv('AI_PROVIDER', 'gemini')

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / 'downloads'
CLIPS_DIR = BASE_DIR / 'clips'
SUBTITLES_DIR = BASE_DIR / 'subtitles'
SCRIPTS_DIR = BASE_DIR / 'scripts'
AUDIO_DIR = BASE_DIR / 'audio'
OUTPUT_DIR = BASE_DIR / 'output'

for _d in [DOWNLOADS_DIR, CLIPS_DIR, SUBTITLES_DIR, SCRIPTS_DIR, AUDIO_DIR, OUTPUT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
