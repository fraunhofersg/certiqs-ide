import {
	DEFAULT_CHART_OVERLAY,
	METRIC_CHART_TOOLBAR,
	type ChartCardToolbarConfig,
	type ChartOverlayDefaults,
} from './metric-charts';

export type { ChartCardToolbarConfig };
export type ChartOverlayState = ChartOverlayDefaults;

export { DEFAULT_CHART_OVERLAY, METRIC_CHART_TOOLBAR };

export function chartToolbarFor(metricKey: string): ChartCardToolbarConfig | null {
	return METRIC_CHART_TOOLBAR[metricKey] ?? null;
}

export function chartOverlayDefaultsFor(metricKey: string): ChartOverlayState {
	const cfg = METRIC_CHART_TOOLBAR[metricKey];
	if (!cfg) {
		return { ...DEFAULT_CHART_OVERLAY };
	}
	return {
		ranges: cfg.ranges ?? DEFAULT_CHART_OVERLAY.ranges,
		lines: cfg.lines === true,
		trend: cfg.trend ?? DEFAULT_CHART_OVERLAY.trend,
		series: cfg.series ?? DEFAULT_CHART_OVERLAY.series,
	};
}

export function resolveChartOverlay(stored: Partial<ChartOverlayState> | undefined, metricKey?: string): ChartOverlayState {
	const base = metricKey ? chartOverlayDefaultsFor(metricKey) : { ...DEFAULT_CHART_OVERLAY };
	return { ...base, ...stored };
}
