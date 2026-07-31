from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
CHECKPOINT = MODEL_DIR / "sam2.1_hiera_tiny.pt"
MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"
MODEL_LOCK = threading.Lock()

app = FastAPI(title="OpenCut SAM 2.1 Local", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


def _require_runtime() -> None:
    if not CHECKPOINT.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Chưa có checkpoint SAM 2.1 Tiny. Hãy chạy setup-windows.ps1 "
                "trong services/sam21 trước."
            ),
        )
    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            status_code=503,
            detail="Không tìm thấy FFmpeg trong PATH.",
        )


@lru_cache(maxsize=1)
def _image_predictor():
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    model = build_sam2(MODEL_CONFIG, str(CHECKPOINT), device="cpu")
    model.eval()
    return SAM2ImagePredictor(model)


@lru_cache(maxsize=1)
def _video_predictor():
    from sam2.build_sam import build_sam2_video_predictor

    predictor = build_sam2_video_predictor(
        MODEL_CONFIG,
        str(CHECKPOINT),
        device="cpu",
    )
    predictor.eval()
    return predictor


def _safe_stem(name: str | None) -> str:
    stem = Path(name or "media").stem
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-")
    return cleaned[:80] or "media"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Màu nền không hợp lệ.")
    raw = match.group(1)
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))


def _write_upload(upload: UploadFile, target: Path) -> None:
    upload.file.seek(0)
    with target.open("wb") as output:
        shutil.copyfileobj(upload.file, output)


def _composite(
    rgb: np.ndarray,
    mask: np.ndarray,
    mode: str,
    color: tuple[int, int, int],
    background: Image.Image | None,
) -> Image.Image:
    foreground = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    alpha = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    if mode == "transparent":
        foreground.putalpha(alpha)
        return foreground

    if mode == "color":
        base = Image.new("RGB", foreground.size, color)
    elif mode == "image" and background is not None:
        base = background.convert("RGB").resize(foreground.size, Image.Resampling.LANCZOS)
    else:
        raise HTTPException(status_code=400, detail="Chế độ nền không hợp lệ.")
    base.paste(foreground, mask=alpha)
    return base


def _segment_image(
    input_path: Path,
    output_path: Path,
    point_x: float,
    point_y: float,
    mode: str,
    color: tuple[int, int, int],
    background: Image.Image | None,
) -> None:
    image = np.asarray(Image.open(input_path).convert("RGB"))
    height, width = image.shape[:2]
    predictor = _image_predictor()
    with MODEL_LOCK, torch.inference_mode():
        predictor.set_image(image)
        masks, scores, _ = predictor.predict(
            point_coords=np.asarray([[point_x * width, point_y * height]], dtype=np.float32),
            point_labels=np.asarray([1], dtype=np.int32),
            multimask_output=True,
        )
    mask = masks[int(np.argmax(scores))]
    result = _composite(image, mask, mode, color, background)
    result.save(output_path, "PNG", optimize=True)


def _extract_frames(input_path: Path, frames_dir: Path) -> float:
    capture = cv2.VideoCapture(str(input_path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vsync",
        "0",
        "-q:v",
        "2",
        str(frames_dir / "%06d.jpg"),
    ]
    subprocess.run(command, check=True)
    return float(fps)


def _encode_frames(
    frames_dir: Path,
    input_path: Path,
    output_path: Path,
    fps: float,
    transparent: bool,
) -> None:
    silent_path = output_path.with_name(f"silent{output_path.suffix}")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        f"{fps:.6f}",
        "-i",
        str(frames_dir / "%06d.png"),
        "-an",
    ]
    if transparent:
        command += [
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuva420p",
            "-b:v",
            "0",
            "-crf",
            "24",
        ]
    else:
        command += [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
        ]
    command += ["-y", str(silent_path)]
    subprocess.run(command, check=True)

    mux_command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(silent_path),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "libopus" if transparent else "aac",
        "-shortest",
        "-y",
        str(output_path),
    ]
    subprocess.run(mux_command, check=True)


def _segment_video(
    input_path: Path,
    output_path: Path,
    point_x: float,
    point_y: float,
    mode: str,
    color: tuple[int, int, int],
    background: Image.Image | None,
    work_dir: Path,
) -> None:
    source_frames = work_dir / "source-frames"
    output_frames = work_dir / "output-frames"
    source_frames.mkdir()
    output_frames.mkdir()
    fps = _extract_frames(input_path, source_frames)
    frame_paths = sorted(source_frames.glob("*.jpg"))
    if not frame_paths:
        raise HTTPException(status_code=400, detail="Video không có khung hình đọc được.")

    first = np.asarray(Image.open(frame_paths[0]).convert("RGB"))
    height, width = first.shape[:2]
    predictor = _video_predictor()
    masks_by_frame: dict[int, np.ndarray] = {}

    with MODEL_LOCK, torch.inference_mode():
        state = predictor.init_state(video_path=str(source_frames))
        predictor.add_new_points_or_box(
            inference_state=state,
            frame_idx=0,
            obj_id=1,
            points=np.asarray([[point_x * width, point_y * height]], dtype=np.float32),
            labels=np.asarray([1], dtype=np.int32),
        )
        for frame_index, object_ids, mask_logits in predictor.propagate_in_video(state):
            object_index = list(object_ids).index(1)
            masks_by_frame[int(frame_index)] = (
                mask_logits[object_index].detach().cpu().numpy().squeeze() > 0
            )
        predictor.reset_state(state)

    for index, frame_path in enumerate(frame_paths):
        rgb = np.asarray(Image.open(frame_path).convert("RGB"))
        mask = masks_by_frame.get(index)
        if mask is None:
            mask = np.zeros(rgb.shape[:2], dtype=bool)
        result = _composite(rgb, mask, mode, color, background)
        result.save(output_frames / f"{index + 1:06d}.png", "PNG")

    _encode_frames(output_frames, input_path, output_path, fps, mode == "transparent")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": "sam2.1_hiera_tiny",
        "device": "cpu",
        "modelLoaded": _image_predictor.cache_info().currsize > 0
        or _video_predictor.cache_info().currsize > 0,
        "checkpointReady": CHECKPOINT.exists(),
        "ffmpegReady": shutil.which("ffmpeg") is not None,
    }


@app.post("/v1/remove-background")
def remove_background(
    media: UploadFile = File(...),
    point_x: float = Form(..., ge=0.0, le=1.0),
    point_y: float = Form(..., ge=0.0, le=1.0),
    background_mode: str = Form("transparent"),
    background_color: str = Form("#00ff00"),
    background_image: UploadFile | None = File(None),
):
    _require_runtime()
    if background_mode not in {"transparent", "color", "image"}:
        raise HTTPException(status_code=400, detail="Chế độ nền không được hỗ trợ.")
    if background_mode == "image" and background_image is None:
        raise HTTPException(status_code=400, detail="Chưa chọn ảnh nền mới.")

    color = _hex_to_rgb(background_color)
    work_dir = Path(tempfile.mkdtemp(prefix="opencut-sam21-"))
    input_suffix = Path(media.filename or "media.bin").suffix or ".bin"
    input_path = work_dir / f"input{input_suffix}"
    _write_upload(media, input_path)

    background = None
    if background_image is not None:
        bg_suffix = Path(background_image.filename or "background.png").suffix or ".png"
        bg_path = work_dir / f"background{bg_suffix}"
        _write_upload(background_image, bg_path)
        background = Image.open(bg_path).convert("RGB")

    is_image = (media.content_type or "").startswith("image/")
    stem = _safe_stem(media.filename)
    output_suffix = ".png" if is_image else (".webm" if background_mode == "transparent" else ".mp4")
    output_path = work_dir / f"{stem}-tach-nen{output_suffix}"

    try:
        if is_image:
            _segment_image(
                input_path,
                output_path,
                point_x,
                point_y,
                background_mode,
                color,
                background,
            )
            media_type = "image/png"
        else:
            _segment_video(
                input_path,
                output_path,
                point_x,
                point_y,
                background_mode,
                color,
                background,
                work_dir,
            )
            media_type = "video/webm" if output_suffix == ".webm" else "video/mp4"
    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except subprocess.CalledProcessError as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"FFmpeg xử lý thất bại: {error}") from error
    except Exception as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"SAM 2.1 xử lý thất bại: {error}") from error

    return FileResponse(
        output_path,
        media_type=media_type,
        filename=output_path.name,
        background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
    )
