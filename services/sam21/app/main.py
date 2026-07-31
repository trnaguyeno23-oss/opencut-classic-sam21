from __future__ import annotations

import json
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
    alpha = Image.fromarray(
        np.clip(mask.astype(np.float32) * 255, 0, 255).astype(np.uint8), mode="L"
    )
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


def _parse_points(
    points_json: str | None,
    point_x: float | None,
    point_y: float | None,
) -> list[dict[str, float | int]]:
    if points_json:
        try:
            raw_points = json.loads(points_json)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="Danh sách điểm chọn không hợp lệ.") from error
    elif point_x is not None and point_y is not None:
        raw_points = [{"x": point_x, "y": point_y, "label": 1, "subjectId": 1}]
    else:
        raw_points = []

    points: list[dict[str, float | int]] = []
    for raw in raw_points:
        if not isinstance(raw, dict):
            continue
        try:
            x = float(raw["x"])
            y = float(raw["y"])
            label = 1 if int(raw.get("label", 1)) else 0
            subject_id = max(1, int(raw.get("subjectId", 1)))
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            points.append({"x": x, "y": y, "label": label, "subjectId": subject_id})

    if not points or not any(point["label"] == 1 for point in points):
        raise HTTPException(status_code=400, detail="Hãy thêm ít nhất một điểm giữ chủ thể.")
    return points


def _group_points(
    points: list[dict[str, float | int]], width: int, height: int
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    grouped: dict[int, list[dict[str, float | int]]] = {}
    for point in points:
        grouped.setdefault(int(point["subjectId"]), []).append(point)
    result: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for subject_id, subject_points in grouped.items():
        if not any(point["label"] == 1 for point in subject_points):
            continue
        coords = np.asarray(
            [[float(point["x"]) * width, float(point["y"]) * height] for point in subject_points],
            dtype=np.float32,
        )
        labels = np.asarray([int(point["label"]) for point in subject_points], dtype=np.int32)
        result[subject_id] = (coords, labels)
    return result


def _refine_mask(mask: np.ndarray, edge_expand: int, edge_feather: int) -> np.ndarray:
    refined = mask.astype(np.uint8) * 255
    if edge_expand:
        kernel_size = abs(edge_expand) * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        refined = (
            cv2.dilate(refined, kernel, iterations=1)
            if edge_expand > 0
            else cv2.erode(refined, kernel, iterations=1)
        )
    if edge_feather:
        blur_size = edge_feather * 2 + 1
        refined = cv2.GaussianBlur(refined, (blur_size, blur_size), 0)
    return refined.astype(np.float32) / 255.0


def _segment_image(
    input_path: Path,
    output_path: Path,
    points: list[dict[str, float | int]],
    mode: str,
    color: tuple[int, int, int],
    background: Image.Image | None,
    edge_expand: int,
    edge_feather: int,
) -> None:
    image = np.asarray(Image.open(input_path).convert("RGB"))
    height, width = image.shape[:2]
    predictor = _image_predictor()
    with MODEL_LOCK, torch.inference_mode():
        predictor.set_image(image)
        combined = np.zeros((height, width), dtype=bool)
        for coords, labels in _group_points(points, width, height).values():
            masks, scores, _ = predictor.predict(
                point_coords=coords,
                point_labels=labels,
                multimask_output=True,
            )
            combined |= masks[int(np.argmax(scores))]
    mask = _refine_mask(combined, edge_expand, edge_feather)
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
    points: list[dict[str, float | int]],
    mode: str,
    color: tuple[int, int, int],
    background: Image.Image | None,
    work_dir: Path,
    edge_expand: int,
    edge_feather: int,
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
        grouped = _group_points(points, width, height)
        for subject_id, (coords, labels) in grouped.items():
            predictor.add_new_points_or_box(
                inference_state=state,
                frame_idx=0,
                obj_id=subject_id,
                points=coords,
                labels=labels,
            )
        for frame_index, object_ids, mask_logits in predictor.propagate_in_video(state):
            combined = np.zeros((height, width), dtype=bool)
            for object_index, _object_id in enumerate(object_ids):
                combined |= mask_logits[object_index].detach().cpu().numpy().squeeze() > 0
            masks_by_frame[int(frame_index)] = combined
        predictor.reset_state(state)

    for index, frame_path in enumerate(frame_paths):
        rgb = np.asarray(Image.open(frame_path).convert("RGB"))
        mask = masks_by_frame.get(index)
        if mask is None:
            mask = np.zeros(rgb.shape[:2], dtype=bool)
        refined = _refine_mask(mask, edge_expand, edge_feather)
        result = _composite(rgb, refined, mode, color, background)
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


@app.post("/v1/preview-mask")
def preview_mask(
    media: UploadFile = File(...),
    points_json: str = Form(...),
    edge_expand: int = Form(0, ge=-12, le=12),
    edge_feather: int = Form(2, ge=0, le=20),
):
    _require_runtime()
    points = _parse_points(points_json, None, None)
    work_dir = Path(tempfile.mkdtemp(prefix="opencut-sam21-preview-"))
    input_suffix = Path(media.filename or "media.bin").suffix or ".bin"
    input_path = work_dir / f"input{input_suffix}"
    preview_input = work_dir / "preview-input.png"
    output_path = work_dir / "mask-preview.png"
    _write_upload(media, input_path)

    try:
        is_image = (media.content_type or "").startswith("image/")
        if is_image:
            image = np.asarray(Image.open(input_path).convert("RGB"))
        else:
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(input_path),
                "-frames:v", "1", "-y", str(preview_input),
            ]
            subprocess.run(command, check=True)
            image = np.asarray(Image.open(preview_input).convert("RGB"))

        height, width = image.shape[:2]
        predictor = _image_predictor()
        with MODEL_LOCK, torch.inference_mode():
            predictor.set_image(image)
            combined = np.zeros((height, width), dtype=bool)
            for coords, labels in _group_points(points, width, height).values():
                masks, scores, _ = predictor.predict(
                    point_coords=coords,
                    point_labels=labels,
                    multimask_output=True,
                )
                combined |= masks[int(np.argmax(scores))]
        mask = _refine_mask(combined, edge_expand, edge_feather)[..., None]
        cyan = np.zeros_like(image, dtype=np.float32)
        cyan[:, :] = (20, 210, 235)
        preview = image.astype(np.float32) * (1 - mask * 0.48) + cyan * mask * 0.48
        Image.fromarray(np.clip(preview, 0, 255).astype(np.uint8)).save(output_path, "PNG")
    except Exception as error:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được xem trước: {error}") from error

    return FileResponse(
        output_path,
        media_type="image/png",
        filename="mask-preview.png",
        background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
    )


@app.post("/v1/remove-background")
def remove_background(
    media: UploadFile = File(...),
    point_x: float | None = Form(None, ge=0.0, le=1.0),
    point_y: float | None = Form(None, ge=0.0, le=1.0),
    points_json: str | None = Form(None),
    background_mode: str = Form("transparent"),
    background_color: str = Form("#00ff00"),
    background_image: UploadFile | None = File(None),
    edge_expand: int = Form(0, ge=-12, le=12),
    edge_feather: int = Form(2, ge=0, le=20),
):
    _require_runtime()
    if background_mode not in {"transparent", "color", "image"}:
        raise HTTPException(status_code=400, detail="Chế độ nền không được hỗ trợ.")
    if background_mode == "image" and background_image is None:
        raise HTTPException(status_code=400, detail="Chưa chọn ảnh nền mới.")

    color = _hex_to_rgb(background_color)
    points = _parse_points(points_json, point_x, point_y)
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
                points,
                background_mode,
                color,
                background,
                edge_expand,
                edge_feather,
            )
            media_type = "image/png"
        else:
            _segment_video(
                input_path,
                output_path,
                points,
                background_mode,
                color,
                background,
                work_dir,
                edge_expand,
                edge_feather,
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
