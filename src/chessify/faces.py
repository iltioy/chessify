"""Аватары сторон из кадров сцены.

В сцене-дуэли камера обычно показывает того, кто говорит. Берём кадры из середины реплик
каждой стороны, находим лица (YuNet), получаем их «отпечатки» (SFace) и группируем похожие.
Стороне достаётся группа лиц, которая чаще видна на её репликах и реже — на репликах соперника.
"""

import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from chessify.schema import Move, Side

MODELS_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
DETECTOR = "face_detection_yunet/face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface/face_recognition_sface_2021dec.onnx"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "chessify"
SAME_PERSON = 0.36  # порог косинусного сходства SFace для «тот же человек»
SAMPLES_PER_MOVE = 3

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # только ошибки: предупреждения бэкенда DNN для пользователя бесполезны


def _model(rel: str) -> str:
    path = CACHE / Path(rel).name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODELS_URL + rel, path)
    return str(path)


@dataclass
class Face:
    side: Side
    crop: np.ndarray
    feature: np.ndarray
    quality: float  # уверенность детектора × размер лица


def _frame(video: Path, t: float) -> np.ndarray | None:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    ).stdout
    return cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR) if out else None


def _square_crop(img: np.ndarray, box: np.ndarray, pad: float = 0.45) -> np.ndarray:
    x, y, w, h = box[:4]
    side = max(w, h) * (1 + 2 * pad)
    cx, cy = x + w / 2, y + h / 2 - h * 0.08  # чуть выше центра: в кадр попадает лоб, а не шея
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    x1, y1 = int(min(img.shape[1], cx + side / 2)), int(min(img.shape[0], cy + side / 2))
    return cv2.resize(img[y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_AREA)


def collect_faces(video: Path, moves: list[Move]) -> list[Face]:
    detector = cv2.FaceDetectorYN.create(_model(DETECTOR), "", (320, 320), 0.8)
    recognizer = cv2.FaceRecognizerSF.create(_model(RECOGNIZER), "")
    faces = []
    for m in moves:
        for k in range(SAMPLES_PER_MOVE):
            t = m.t0 + (m.t1 - m.t0) * (k + 1) / (SAMPLES_PER_MOVE + 1)
            img = _frame(video, t)
            if img is None:
                continue
            detector.setInputSize((img.shape[1], img.shape[0]))
            _, found = detector.detect(img)
            if found is None:
                continue
            # Говорящий обычно самый крупный в кадре.
            best = max(found, key=lambda f: f[2] * f[3])
            if best[2] < img.shape[1] * 0.06:  # слишком мелко — общий план
                continue
            aligned = recognizer.alignCrop(img, best)
            feat = recognizer.feature(aligned).flatten()
            feat = feat / (np.linalg.norm(feat) + 1e-9)
            faces.append(Face(m.side, _square_crop(img, best), feat, float(best[-1]) * float(best[2] * best[3])))
    return faces


def _cluster(faces: list[Face]) -> list[list[Face]]:
    clusters: list[list[Face]] = []
    for f in sorted(faces, key=lambda f: -f.quality):
        for c in clusters:
            if float(np.dot(c[0].feature, f.feature)) > SAME_PERSON:
                c.append(f)
                break
        else:
            clusters.append([f])
    return clusters


def pick_avatars(faces: list[Face]) -> dict[Side, np.ndarray]:
    clusters = _cluster(faces)
    result: dict[Side, np.ndarray] = {}
    taken: set[int] = set()

    def score(c: list[Face], side: Side) -> int:
        return sum(f.side == side for f in c) - sum(f.side != side for f in c)

    # Сначала сторона с более однозначным лицом, чтобы две стороны не забрали одну группу.
    for side in sorted(Side, key=lambda s: -max((score(c, s) for c in clusters), default=0)):
        ranked = sorted((i for i in range(len(clusters)) if i not in taken), key=lambda i: -score(clusters[i], side))
        if ranked and score(clusters[ranked[0]], side) > 0:
            taken.add(ranked[0])
            result[side] = max(clusters[ranked[0]], key=lambda f: f.quality).crop
    return result


def make_avatars(video: Path, moves: list[Move], out_dir: Path) -> dict[Side, Path]:
    paths = {}
    for side, crop in pick_avatars(collect_faces(video, moves)).items():
        path = out_dir / f"avatar_{side.value}.png"
        cv2.imwrite(str(path), crop)
        paths[side] = path
    return paths
