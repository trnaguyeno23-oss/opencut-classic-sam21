const DEFAULT_SERVICE_URL = "http://127.0.0.1:8788";

export type BackgroundMode = "transparent" | "color" | "image";

export type ServiceHealth = {
	status: "ok";
	model: string;
	device: string;
	modelLoaded: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function getServiceUrl(): string {
	return (
		process.env.NEXT_PUBLIC_SAM21_SERVICE_URL?.replace(/\/$/, "") ??
		DEFAULT_SERVICE_URL
	);
}

export async function checkSamService(): Promise<ServiceHealth> {
	const response = await fetch(`${getServiceUrl()}/health`, {
		signal: AbortSignal.timeout(3_000),
	});
	if (!response.ok) {
		throw new Error("Dịch vụ SAM 2.1 chưa sẵn sàng");
	}
	const payload: unknown = await response.json();
	if (
		!isRecord(payload) ||
		payload.status !== "ok" ||
		typeof payload.model !== "string" ||
		typeof payload.device !== "string" ||
		typeof payload.modelLoaded !== "boolean"
	) {
		throw new Error("Dịch vụ SAM 2.1 trả về dữ liệu không hợp lệ");
	}
	return {
		status: "ok",
		model: payload.model,
		device: payload.device,
		modelLoaded: payload.modelLoaded,
	};
}

export async function removeBackground({
	file,
	point,
	mode,
	backgroundColor,
	backgroundImage,
}: {
	file: File;
	point: { x: number; y: number };
	mode: BackgroundMode;
	backgroundColor: string;
	backgroundImage?: File;
}): Promise<File> {
	const body = new FormData();
	body.append("media", file, file.name);
	body.append("point_x", point.x.toString());
	body.append("point_y", point.y.toString());
	body.append("background_mode", mode);
	body.append("background_color", backgroundColor);
	if (backgroundImage) {
		body.append("background_image", backgroundImage, backgroundImage.name);
	}

	const response = await fetch(`${getServiceUrl()}/v1/remove-background`, {
		method: "POST",
		body,
	});
	if (!response.ok) {
		let message = "Không thể tách nền";
		try {
			const payload: unknown = await response.json();
			if (isRecord(payload) && typeof payload.detail === "string") {
				message = payload.detail;
			}
		} catch {
			// Keep the friendly fallback when the local service returns plain text.
		}
		throw new Error(message);
	}

	const blob = await response.blob();
	const disposition = response.headers.get("content-disposition") ?? "";
	const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
	const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
	const fallbackExtension = file.type.startsWith("image/") ? "png" : "webm";
	const fallbackBase = file.name.replace(/\.[^.]+$/, "");
	const name = encodedName
		? decodeURIComponent(encodedName)
		: (plainName ?? `${fallbackBase}-tach-nen.${fallbackExtension}`);

	return new File([blob], name, {
		type: blob.type || (fallbackExtension === "png" ? "image/png" : "video/webm"),
	});
}
