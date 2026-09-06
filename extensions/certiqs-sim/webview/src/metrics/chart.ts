export const LIVE_CHART_LINE_PROPS = {
	isAnimationActive: false,
	animationDuration: 0,
	dot: false,
	activeDot: { r: 2 },
} as const;

export const MAX_CHART_POINTS = 500;
export const CHART_REF_SHOTS = 100_000;
export const CHART_REF_WINDOW = 120;
export const CHART_MIN_WINDOW = 40;

function clamp(n: number, lo: number, hi: number): number {
	return Math.min(hi, Math.max(lo, n));
}

export function chartBaseWindow(shotsPerWindow: number): number {
	const shots = Math.max(Number(shotsPerWindow) || CHART_REF_SHOTS, 1);
	const raw = Math.round(CHART_REF_WINDOW * (CHART_REF_SHOTS / shots));
	return clamp(raw, CHART_MIN_WINDOW, MAX_CHART_POINTS);
}

export function chartWindowCapacity(pointCount: number, baseWindow: number, max = MAX_CHART_POINTS): number {
	const base = Math.max(1, Math.floor(baseWindow) || 1);
	if (pointCount <= 0) {
		return Math.min(base, max);
	}
	const pages = Math.max(1, Math.ceil(pointCount / base));
	return Math.min(pages * base, max);
}

export function chartWindow<T>(points: T[], shotsPerWindow: number, max = MAX_CHART_POINTS): T[] {
	if (!points.length) {
		return points;
	}
	const base = chartBaseWindow(shotsPerWindow);
	const capacity = chartWindowCapacity(points.length, base, max);
	if (points.length <= capacity) {
		return points;
	}
	return points.slice(points.length - capacity);
}

export type ChartEpochPoint = { epoch: number };

export function chartXDomain(points: ChartEpochPoint[], shotsPerWindow: number, max = MAX_CHART_POINTS): [number, number] {
	const base = chartBaseWindow(shotsPerWindow);
	const capacity = chartWindowCapacity(points.length, base, max);
	if (!points.length) {
		return [0, Math.max(capacity - 1, 1)];
	}
	const visible = points.length <= capacity ? points : points.slice(points.length - capacity);
	const start = visible[0]?.epoch;
	const xMin = Number.isFinite(start) ? Number(start) : 0;
	return [xMin, xMin + Math.max(capacity - 1, 1)];
}
