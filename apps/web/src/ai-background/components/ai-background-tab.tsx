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
	previewMask,
	removeBackground,
	type BackgroundMode,
	type SelectionPoint,
} from "../service";

type MarkerPoint = SelectionPoint & { markerX: number; markerY: number };
type Subject = { id: number; name: string; color: string; points: MarkerPoint[] };
type PointMode = "keep" | "remove";

const SUBJECT_COLORS = ["#8b5cf6", "#06b6d4", "#f59e0b", "#22c55e", "#ec4899", "#3b82f6"];
const MODES: Array<{ id: BackgroundMode; label: string }> = [
	{ id: "transparent", label: "Trong suốt" },
	{ id: "color", label: "Màu đơn" },
	{ id: "image", label: "Ảnh nền" },
];

function makeSubject(id: number): Subject {
	return {
		id,
		name: `Chủ thể ${id}`,
		color: SUBJECT_COLORS[(id - 1) % SUBJECT_COLORS.length]!,
		points: [],
	};
}

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
	const [subjects, setSubjects] = useState<Subject[]>([makeSubject(1)]);
	const [activeSubjectId, setActiveSubjectId] = useState(1);
	const [pointMode, setPointMode] = useState<PointMode>("keep");
	const [mode, setMode] = useState<BackgroundMode>("transparent");
	const [backgroundColor, setBackgroundColor] = useState("#00ff00");
	const [backgroundImage, setBackgroundImage] = useState<File>();
	const [edgeExpand, setEdgeExpand] = useState(0);
	const [edgeFeather, setEdgeFeather] = useState(2);
	const [serviceState, setServiceState] = useState<"checking" | "online" | "offline">("checking");
	const [isProcessing, setIsProcessing] = useState(false);
	const [isPreviewing, setIsPreviewing] = useState(false);
	const [maskPreviewUrl, setMaskPreviewUrl] = useState<string>();
	const previewRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		let cancelled = false;
		checkSamService()
			.then(() => !cancelled && setServiceState("online"))
			.catch(() => !cancelled && setServiceState("offline"));
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		return () => {
			if (maskPreviewUrl) URL.revokeObjectURL(maskPreviewUrl);
		};
	}, [maskPreviewUrl]);

	const sourcePreviewUrl = useMemo(
		() => mediaAsset?.thumbnailUrl ?? mediaAsset?.url,
		[mediaAsset?.thumbnailUrl, mediaAsset?.url],
	);
	const allPoints = useMemo(() => subjects.flatMap((subject) => subject.points), [subjects]);
	const hasKeepPoint = allPoints.some((point) => point.label === 1);

	const clearMaskPreview = () => {
		if (maskPreviewUrl) URL.revokeObjectURL(maskPreviewUrl);
		setMaskPreviewUrl(undefined);
	};

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
		const newPoint: MarkerPoint = {
			x: Math.min(1, Math.max(0, sourceX)),
			y: Math.min(1, Math.max(0, sourceY)),
			label: pointMode === "keep" ? 1 : 0,
			subjectId: activeSubjectId,
			markerX: rawX,
			markerY: rawY,
		};
		setSubjects((current) =>
			current.map((subject) =>
				subject.id === activeSubjectId
					? { ...subject, points: [...subject.points, newPoint] }
					: subject,
			),
		);
		clearMaskPreview();
	};

	const addSubject = () => {
		const nextId = Math.max(0, ...subjects.map((subject) => subject.id)) + 1;
		setSubjects((current) => [...current, makeSubject(nextId)]);
		setActiveSubjectId(nextId);
		setPointMode("keep");
		clearMaskPreview();
	};

	const removeActiveSubject = () => {
		if (subjects.length === 1) {
			setSubjects([makeSubject(1)]);
			setActiveSubjectId(1);
		} else {
			const remaining = subjects.filter((subject) => subject.id !== activeSubjectId);
			setSubjects(remaining);
			setActiveSubjectId(remaining[0]!.id);
		}
		clearMaskPreview();
	};

	const undoPoint = () => {
		setSubjects((current) =>
			current.map((subject) =>
				subject.id === activeSubjectId
					? { ...subject, points: subject.points.slice(0, -1) }
					: subject,
			),
		);
		clearMaskPreview();
	};

	const handlePreview = async () => {
		if (!mediaAsset || !hasKeepPoint) return;
		setIsPreviewing(true);
		try {
			const blob = await previewMask({
				file: mediaAsset.file,
				points: allPoints,
				edgeExpand,
				edgeFeather,
			});
			clearMaskPreview();
			setMaskPreviewUrl(URL.createObjectURL(blob));
		} catch (error) {
			toast.error("Xem trước thất bại", {
				description: error instanceof Error ? error.message : undefined,
			});
		} finally {
			setIsPreviewing(false);
		}
	};

	const handleProcess = async () => {
		if (!mediaAsset || !activeProject || !hasKeepPoint) return;
		if (mode === "image" && !backgroundImage) {
			toast.error("Hãy chọn ảnh nền trước");
			return;
		}
		setIsProcessing(true);
		try {
			const output = await removeBackground({
				file: mediaAsset.file,
				points: allPoints,
				mode,
				backgroundColor,
				backgroundImage,
				edgeExpand,
				edgeFeather,
			});
			const [processed] = await processMediaAssets({ files: [output] });
			if (!processed) throw new Error("Không đọc được kết quả từ SAM 2.1");
			await editor.media.addMediaAsset({
				projectId: activeProject.metadata.id,
				asset: processed,
			});
			toast.success("Đã tách chủ thể và thêm kết quả vào kho Media");
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
			<SectionContent className="space-y-3 border-l border-zinc-800 bg-zinc-950 p-3 text-zinc-100">
				<div>
					<h3 className="text-sm font-semibold">Tách chủ thể bằng SAM 2.1</h3>
					<p className="mt-1 text-xs text-zinc-400">
						Chọn chủ thể, rồi chấm điểm giữ hoặc điểm loại trực tiếp trên ảnh.
					</p>
				</div>

				<Button variant="outline" size="sm" onClick={addSubject} className="w-full border-zinc-700 bg-zinc-900 text-zinc-100">
					+ Thêm chủ thể
				</Button>

				<div className="flex flex-wrap gap-1.5">
					{subjects.map((subject) => (
						<button
							key={subject.id}
							type="button"
							onClick={() => setActiveSubjectId(subject.id)}
							className={cn(
								"rounded-full border px-2.5 py-1 text-[11px]",
								activeSubjectId === subject.id ? "border-transparent text-white" : "border-zinc-700 bg-zinc-900 text-zinc-300",
							)}
							style={activeSubjectId === subject.id ? { backgroundColor: subject.color } : undefined}
						>
							{subject.name} · {subject.points.length} điểm
						</button>
					))}
					<button type="button" onClick={removeActiveSubject} className="rounded-full border border-red-900 px-2.5 py-1 text-[11px] text-red-400">
						Xóa
					</button>
				</div>

				<div className="grid grid-cols-2 gap-2">
					<Button size="sm" onClick={() => setPointMode("keep")} className={cn(pointMode === "keep" ? "bg-violet-600" : "bg-zinc-800", "text-white")}>
						+ Giữ thêm
					</Button>
					<Button size="sm" onClick={() => setPointMode("remove")} className={cn(pointMode === "remove" ? "bg-rose-600" : "bg-zinc-800", "text-white")}>
						− Loại nền
					</Button>
				</div>

				<div
					ref={previewRef}
					role="button"
					tabIndex={0}
					onClick={handlePickPoint}
					onKeyDown={(event) => {
						if (event.key === "Enter" || event.key === " ") {
							event.preventDefault();
							const centerPoint: MarkerPoint = {
								x: 0.5,
								y: 0.5,
								label: pointMode === "keep" ? 1 : 0,
								subjectId: activeSubjectId,
								markerX: 0.5,
								markerY: 0.5,
							};
							setSubjects((current) => current.map((subject) =>
								subject.id === activeSubjectId
									? { ...subject, points: [...subject.points, centerPoint] }
									: subject,
							));
							clearMaskPreview();
						}
					}}
					className="relative aspect-video w-full cursor-crosshair overflow-hidden rounded-md border border-zinc-700 bg-zinc-900"
				>
					{maskPreviewUrl || sourcePreviewUrl ? (
						// eslint-disable-next-line @next/next/no-img-element
						<img src={maskPreviewUrl ?? sourcePreviewUrl} alt="Khung hình chọn chủ thể" className="size-full object-contain" />
					) : (
						<div className="flex size-full items-center justify-center text-xs text-zinc-500">Không có ảnh xem trước</div>
					)}
					{subjects.flatMap((subject) =>
						subject.points.map((point, index) => (
							<span
								key={`${subject.id}-${index}`}
								className={cn(
									"absolute flex size-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white text-[9px] font-bold text-white shadow",
									point.label === 0 && "bg-rose-600",
								)}
								style={{
									left: `${point.markerX * 100}%`,
									top: `${point.markerY * 100}%`,
									backgroundColor: point.label === 1 ? subject.color : undefined,
								}}
							>
								{subject.id}
							</span>
						)),
					)}
				</div>

				<div className="flex items-center justify-between text-[11px] text-zinc-400">
					<span>Tím/màu: giữ · Đỏ: loại</span>
					<button type="button" onClick={undoPoint} className="text-cyan-400">Hoàn tác điểm</button>
				</div>

				<div className="space-y-3 rounded-md border border-zinc-800 bg-zinc-900/70 p-3">
					<label htmlFor="sam-edge-expand" className="block text-xs">
						<span className="mb-1 flex justify-between"><span>Bù viền tóc/quần áo</span><span>{edgeExpand}</span></span>
						<input id="sam-edge-expand" aria-label="Bù viền tóc và quần áo" type="range" min={-12} max={12} value={edgeExpand} onChange={(event) => { setEdgeExpand(Number(event.target.value)); clearMaskPreview(); }} className="w-full accent-cyan-400" />
					</label>
					<label htmlFor="sam-edge-feather" className="block text-xs">
						<span className="mb-1 flex justify-between"><span>Độ mềm viền</span><span>{edgeFeather}</span></span>
						<input id="sam-edge-feather" aria-label="Độ mềm viền" type="range" min={0} max={20} value={edgeFeather} onChange={(event) => { setEdgeFeather(Number(event.target.value)); clearMaskPreview(); }} className="w-full accent-cyan-400" />
					</label>
				</div>

				<Button variant="outline" size="sm" onClick={handlePreview} disabled={!hasKeepPoint || isPreviewing || serviceState !== "online"} className="w-full border-zinc-700 bg-zinc-900 text-zinc-100">
					{isPreviewing ? "Đang tạo xem trước..." : "Xem trước vùng tách"}
				</Button>

				<div className="space-y-2">
					<p className="text-xs font-medium">Nền đầu ra</p>
					<div className="grid grid-cols-3 gap-1">
						{MODES.map((item) => (
							<Button key={item.id} variant="outline" size="sm" onClick={() => setMode(item.id)} className={cn("border-zinc-700 px-1 text-xs text-zinc-100", mode === item.id ? "bg-cyan-700" : "bg-zinc-900")}>
								{item.label}
							</Button>
						))}
					</div>
				</div>

				{mode === "color" && (
					<label className="flex items-center justify-between text-xs">Màu nền<input type="color" value={backgroundColor} onChange={(event) => setBackgroundColor(event.target.value)} className="h-8 w-14 rounded border bg-transparent" /></label>
				)}
				{mode === "image" && (
					<label className="block rounded-md border border-dashed border-zinc-700 p-3 text-center text-xs text-zinc-300">
						<span className="mb-2 block">{backgroundImage?.name ?? "Chọn ảnh dùng làm nền mới"}</span>
						<input type="file" accept="image/*" onChange={(event) => setBackgroundImage(event.target.files?.[0])} className="block w-full text-xs" />
					</label>
				)}

				<div className="flex items-center gap-2 text-xs text-zinc-400">
					<span className={cn("size-2 rounded-full", serviceState === "online" && "bg-emerald-500", serviceState === "offline" && "bg-red-500", serviceState === "checking" && "bg-amber-500")} />
					<span>{serviceState === "online" ? "SAM 2.1 Tiny đã sẵn sàng" : serviceState === "offline" ? "Chưa mở dịch vụ SAM 2.1 local" : "Đang kiểm tra dịch vụ..."}</span>
				</div>

				<Button className="w-full bg-gradient-to-r from-violet-600 to-cyan-600 text-white" disabled={!hasKeepPoint || serviceState !== "online" || isProcessing} onClick={handleProcess}>
					{isProcessing ? "Đang tách chủ thể..." : "Tách chủ thể và thay nền"}
				</Button>
				<p className="text-[11px] leading-relaxed text-zinc-500">CPU xử lý video chậm; nên thử xem trước và dùng clip 5–15 giây.</p>
			</SectionContent>
		</Section>
	);
}
