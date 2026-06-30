import sys
from pathlib import Path

# Add backend/ to sys.path so tests can import api, scrape_videos, suggest
sys.path.insert(0, str(Path(__file__).parent.parent))
