# SAM 2.1 background removal

OpenCut's AI background tool is split into two local components:

- The editor UI in `apps/web/src/ai-background` lets the user click a target and choose transparent, solid-color, or image replacement output.
- The Python sidecar in `services/sam21` runs Meta's `sam2.1_hiera_tiny` checkpoint on CPU and returns a processed media file.

The split keeps PyTorch out of the browser bundle and keeps the original media on the user's machine. The service listens only on `127.0.0.1:8788` by default.

## Multi-subject refinement

The editor can keep multiple subjects in one pass. Each subject accepts multiple positive (keep) and negative (remove) prompt points. The local service unions the SAM masks, then optionally expands or erodes and feathers their edges before compositing. `POST /v1/preview-mask` returns a cyan mask overlay for the first image or video frame so users can refine points before processing the full clip.

## Processing contract

`POST /v1/remove-background` accepts multipart form data:

- `media`: source image or video
- `points_json`: normalized points with `x`, `y`, `label`, and `subjectId`
- `edge_expand`: signed mask expansion/erosion in pixels
- `edge_feather`: mask feather radius in pixels
- `background_mode`: `transparent`, `color`, or `image`
- `background_color`: six-digit hex color
- `background_image`: required when mode is `image`

Images are returned as PNG. Transparent videos use VP9 WebM with an alpha channel and Opus audio. Replaced-background videos use H.264 MP4 with AAC audio.

## CPU expectations

The tiny checkpoint was deliberately selected for computers without an NVIDIA GPU. Video propagation is still compute-intensive, so the UI recommends short 720p clips. A later desktop shell can manage the service lifecycle and expose hardware-specific ONNX or DirectML acceleration without changing this HTTP contract.
