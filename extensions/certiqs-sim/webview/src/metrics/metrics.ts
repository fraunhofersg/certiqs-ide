export function metricValue(point: { metrics: Record<string, unknown> }, key: string): number | null {
	const raw = point.metrics[key];
	return typeof raw === 'number' ? raw : null;
}
