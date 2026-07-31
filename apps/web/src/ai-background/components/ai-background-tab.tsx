"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Section, SectionContent } from "@/components/section";
import { useEditor } from "@/editor/use-editor";
import { processMediaAssets } from "@/media/processing";
import type { ImageElement, VideoElement } from "@/timeline";
import { cn } from "@/utils/ui";
import { toast } from "sonner";
import {
	checkSamService,
	removeBackground,
	type BackgroundMode,
} from "../service";

const MODES: Array<{ id: BackgroundMode; label: string }> = [
	{ id: "transparent", label: "Trong suốt" },
	{ id: "color", label: "Màu đơn" },
	{ id: "image", label: "Ảnh nền" },
];

export function AiBackgroundTab({
	element,
}: {
	element: VideoElement | ImageElement;
	trackId: string;
}) {
	const editor = useEditor();
	const activeProject = useEditor((e) => e.project.getActive());
	const mediaAsset = useEditor((e) =>
		e.media.getAssets().find((asset) => asset.id === element.mediaId),
	);
	const [point, setPoint] = useState<{ x: number; y: number } | null>(null);
	const [marker, setMarker] = useState<{ x: number; y: number } | null>(null);
	const [mode, setMode] = useState<BackgroundMode>("transparent");
	const [backgroundColor, setBackgroundColor] = useState("#00ff00");
	const [backgroundImage, setBackgroundImage] = useState<File>();
	const [serviceState, setServiceState] = useState<
		"checking" | "online" | "offline"
	>("checking");
	const [isProcessing, setIsProcessing] = useState(false);
	const previewRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		let cancelled = false;
		checkSamService()
			.then(() => {
				if (!cancelled) setServiceState("online");
			})
			.catch(() => {
				if (!cancelled) setServiceState("offline");
			});
		return () => {
			cancelled = true;
		};
	}, []);

	const previewUrl = useMemo(
		() => mediaAsset?.thumbnailUrl ?? mediaAsset?.url,
		[mediaAsset?.thumbnailUrl, mediaAsset?.url],
	);

	const handlePickPoint = (event: React.MouseEvent<HTMLDivElement>) => {
		const bounds = previewRef.current?.getBoundingClientRect();
		if (!bounds) return;
		const rawX = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
		const rawY = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height));
		const sourceWidth = mediaAsset?.width ?? bounds.width;
		const sourceHeight = mediaAsset?.height ?? bounds.height;
		const sourceAspect = sourceWidth / sourceHeight;
		const boxAspect = bounds.width / bounds.height;
		let sourceX = rawX;
		let sourceY = rawY;
		if (sourceAspect > boxAspect) {
			const renderedHeight = bounds.width / sourceAspect;
			const offsetY = (bounds.height - renderedHeight) / 2;
			sourceY = (event.clientY - bounds.top - offsetY) / renderedHeight;
		} else {
			const renderedWidth = bounds.height * sourceAspect;
			const offsetX = (bounds.width - renderedWidth) / 2;
			sourceX = (event.clientX - bounds.left - offsetX) / renderedWidth;
		}
		setPoint({
			x: Math.min(1, Math.max(0, sourceX)),
			y: Math.min(1, Math.max(0, sourceY)),
		});
		setMarker({ x: rawX, y: rawY });
	};

	const handlePreviewKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
		if (event.key === "Enter" || event.key === " ") {
			event.preventDefault();
			setPoint({ x: 0.5, y: 0.5 });
			setMarker({ x: 0.5, y: 0.5 });
		}
	};

	const handleProcess = async () => {
		if (!mediaAsset || !activeProject || !point) return;
		if (mode === "image" && !backgroundImage) {
			toast.error("Hãy chọn ảnh nền trước");
			return;
		}

		setIsProcessing(true);
		try {
			const output = await removeBackground({
				file: mediaAsset.file,
				point,
				mode,
				backgroundColor,
				backgroundImage,
			});
			const [processed] = await processMediaAssets({ files: [output] });
			if (!processed) throw new Error("Không đọc được kết quả từ SAM 2.1");
			await editor.media.addMediaAsset({
				projectId: activeProject.metadata.id,
				asset: processed,
			});
			toast.success("Đã tách nền và thêm kết quả vào kho Media");
		} catch (error) {
			toast.error("Tách nền thất bại", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setIsProcessing(false);
		}
	};

	return (
		<Section sectionKey={`${element.id}:ai-background`}>
			<SectionContent className="space-y-4 p-3">
				<div>
					<h3 className="text-sm font-medium">Xóa nền bằng SAM 2.1</h3>
					<p className="text-muted-foreground mt-1 text-xs">
						Bấm vào người hoặc vật cần giữ lại. AI sẽ tách chủ thể khỏi nền.
					</p>
				</div>

				<div
					ref={previewRef}
					role="button"
					tabIndex={0}
					onClick={handlePickPoint}
					onKeyDown={handlePreviewKeyDown}
					className="bg-muted relative aspect-video w-full cursor-crosshair overflow-hidden rounded-md border"
				>
					{previewUrl ? (
						// eslint-disable-next-line @next/next/no-img-element
						<img
							src={previewUrl}
							alt="Khung hình để chọn chủ thể"
							className="size-full object-contain"
						/>
					) : (
						<div className="text-muted-foreground flex size-full items-center justify-center text-xs">
							Không có ảnh xem trước
						</div>
					)}
					{marker && (
						<span
							className="absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-blue-500 shadow"
							style={{ left: `${marker.x * 100}%`, top: `${marker.y * 100}%` }}
						/>
					)}
				</div>

				<div className="space-y-2">
					<p className="text-xs font-medium">Nền đầu ra</p>
					<div className="grid grid-cols-3 gap-1">
						{MODES.map((item) => (
							<Button
								key={item.id}
								variant={mode === item.id ? "secondary" : "outline"}
								size="sm"
								onClick={() => setMode(item.id)}
								className="px-1 text-xs"
							>
								{item.label}
							</Button>
						))}
					</div>
				</div>

				{mode === "color" && (
					<label className="flex items-center justify-between text-xs">
						Màu nền
						<input
							type="color"
							value={backgroundColor}
							onChange={(event) => setBackgroundColor(event.target.value)}
							className="h-8 w-14 rounded border bg-transparent"
						/>
					</label>
				)}

				{mode === "image" && (
					<label className="block rounded-md border border-dashed p-3 text-center text-xs">
						<span className="text-muted-foreground block pb-2">
							{backgroundImage?.name ?? "Chọn ảnh dùng làm nền mới"}
						</span>
						<input
							type="file"
							accept="image/*"
							onChange={(event) => setBackgroundImage(event.target.files?.[0])}
							className="block w-full text-xs"
						/>
					</label>
				)}

				<div className="flex items-center gap-2 text-xs">
					<span
						className={cn(
							"size-2 rounded-full",
							serviceState === "online" && "bg-emerald-500",
							serviceState === "offline" && "bg-red-500",
							serviceState === "checking" && "bg-amber-500",
						)}
					/>
					<span className="text-muted-foreground">
						{serviceState === "online"
							? "SAM 2.1 Tiny đã sẵn sàng"
							: serviceState === "offline"
								? "Chưa mở dịch vụ SAM 2.1 local"
								: "Đang kiểm tra dịch vụ..."}
					</span>
				</div>

				<Button
					className="w-full"
					disabled={!point || serviceState !== "online" || isProcessing}
					onClick={handleProcess}
				>
					{isProcessing ? "Đang tách nền..." : "Tách nền AI"}
				</Button>
				<p className="text-muted-foreground text-[11px] leading-relaxed">
					Máy không có NVIDIA sẽ xử lý chậm hơn. Clip ngắn 5–15 giây cho kết quả ổn định nhất.
				</p>
			</SectionContent>
		</Section>
	);
}
