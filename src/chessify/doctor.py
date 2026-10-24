"""Проверка окружения.

На целевой машине (Windows 11 + RTX 5060) проверяет всё, что нельзя проверить в среде
разработки: драйвер, CUDA в PyTorch и CTranslate2, пробное распознавание на GPU, NVENC.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from chessify.paths import RENDER_DIR


@dataclass
class Check:
    name: str
    ok: bool | None  # None — проверка пропущена
    detail: str


def _run(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def check_python() -> Check:
    v = sys.version_info
    return Check("Python 3.12", (v.major, v.minor) == (3, 12), sys.version.split()[0])


def check_ffmpeg() -> Check:
    exe = shutil.which("ffmpeg")
    if not exe:
        return Check("ffmpeg", False, "не найден в PATH")
    first = _run([exe, "-version"]).stdout.splitlines()[0]
    return Check("ffmpeg", True, first)


def check_nvenc() -> Check:
    exe = shutil.which("ffmpeg")
    if not exe:
        return Check("ffmpeg: кодировщик h264_nvenc", None, "ffmpeg не найден")
    if not shutil.which("nvidia-smi"):
        return Check("ffmpeg: кодировщик h264_nvenc", None, "нет GPU NVIDIA — допустимо в среде разработки")
    encoders = _run([exe, "-hide_banner", "-encoders"]).stdout
    if "h264_nvenc" not in encoders:
        return Check("ffmpeg: кодировщик h264_nvenc", False, "в сборке ffmpeg нет NVENC")
    probe = _run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=1",
                  "-c:v", "h264_nvenc", "-f", "null", "-"])
    return Check("ffmpeg: кодировщик h264_nvenc", probe.returncode == 0,
                 "пробное кодирование прошло" if probe.returncode == 0 else probe.stderr.strip()[:200])


def check_node() -> Check:
    exe = shutil.which("node")
    if not exe:
        return Check("Node.js 22+", False, "не найден в PATH")
    v = _run([exe, "-v"]).stdout.strip()
    major = int(v.lstrip("v").split(".")[0])
    return Check("Node.js 22+", major >= 22, v)


def check_remotion() -> Check:
    ok = (RENDER_DIR / "node_modules" / "remotion").is_dir()
    return Check("Remotion установлен (render/node_modules)", ok, "" if ok else "выполните npm ci в папке render")


def check_nvidia_driver() -> Check:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return Check("Драйвер NVIDIA", None, "nvidia-smi не найден (нет GPU — допустимо в среде разработки)")
    out = _run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    return Check("Драйвер NVIDIA", out.returncode == 0, out.stdout.strip() or out.stderr.strip())


def check_torch_cuda() -> Check:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return Check("PyTorch + CUDA", None, "torch не установлен (extra 'diar')")
    if not torch.cuda.is_available():
        return Check("PyTorch + CUDA", False, f"torch {torch.__version__}, CUDA недоступна")
    cap = torch.cuda.get_device_capability(0)
    arch_ok = f"sm_{cap[0]}{cap[1]}" in torch.cuda.get_arch_list()
    return Check("PyTorch + CUDA", arch_ok,
                 f"torch {torch.__version__}, {torch.cuda.get_device_name(0)}, sm_{cap[0]}{cap[1]}"
                 + ("" if arch_ok else " — сборка torch не содержит ядер для этой архитектуры, нужен индекс cu128"))


def check_ctranslate2_gpu() -> Check:
    """Флагов мало: на Blackwell CTranslate2 может молча уйти на CPU, поэтому гоняем реальную модель."""
    try:
        import ctranslate2  # type: ignore[import-not-found]
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        return Check("faster-whisper на GPU", None, "faster-whisper не установлен (extra 'asr')")
    if ctranslate2.get_cuda_device_count() == 0:
        return Check("faster-whisper на GPU", None, "CUDA-устройств не найдено")
    try:
        import numpy as np

        model = WhisperModel("tiny", device="cuda", compute_type="float16")
        segments, _ = model.transcribe(np.zeros(16000 * 5, dtype=np.float32), language="ru")
        list(segments)
    except Exception as e:  # noqa: BLE001 — показываем любую ошибку пользователю
        return Check("faster-whisper на GPU", False, f"пробное распознавание упало: {e}")
    return Check("faster-whisper на GPU", True, f"ctranslate2 {ctranslate2.__version__}, пробное распознавание прошло")


CHECKS: list[Callable[[], Check]] = [
    check_python,
    check_ffmpeg,
    check_nvenc,
    check_node,
    check_remotion,
    check_nvidia_driver,
    check_torch_cuda,
    check_ctranslate2_gpu,
]


def run_all() -> list[Check]:
    results = []
    for fn in CHECKS:
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001
            results.append(Check(fn.__name__, False, f"ошибка проверки: {e}"))
    return results
