from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER_DIR = ROOT / "render"
GENERATED_DIR = RENDER_DIR / "src" / "generated"
JOBS_DIR = ROOT / "jobs"
FIXTURES_DIR = ROOT / "fixtures"
MUSIC_DIR = RENDER_DIR / "public" / "music"  # библиотека фоновой музыки (в Docker — том data/music)
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
