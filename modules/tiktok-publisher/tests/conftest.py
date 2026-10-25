"""Тесты запускаются без установки пакета: src — в путь импорта."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
