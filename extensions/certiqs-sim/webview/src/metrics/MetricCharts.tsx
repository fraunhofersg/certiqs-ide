import { Card } from '@heroui/react';
import { memo, useMemo, type ReactNode } from 'react';
import { ReferenceArea, ReferenceLine } from 'recharts';
import type { DataPoint, MetricCatalogEntry } from '../../../src/apiTypes';
import { ChartCardSettings } from './ChartCardSettings';
import { MetricLineChart } from './MetricLineChart';
import { chartToolbarFor, resolveChartOverlay, type ChartOverlayState } from './chart-card-settings';
import {
	LEVEL_COLOR,
	abortMinUpper,
	emaTrendValues,
	rangeGuideFromCatalog,
	yDomainForPositiveValues,
	yDomainForSeries,
	yTicksForDomain,
	type MetricRangeGuide,
} from './chart-ranges';
import { LIVE_CHART_LINE_PROPS, chartWindow, chartXDomain } from './chart';
import type { ChartColumnCount } from './columns';
import { metricValue } from './metrics';

const CHART_GRID_CLASS: Record<ChartColumnCount, string> = {
	2: 'grid-cols-1 md:grid-cols-2',
	4: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4',
	6: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6',
	8: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8',
};

const SERIES_STROKE = 'var(--accent)';
const TREND_HALF_LIFE_EPOCHS = 10;
const AXIS_TICK = { fontSize: 11, fill: 'var(--muted)' } as const;

type MetricChartPanelProps = {
	metric: MetricCatalogEntry;
	points: DataPoint[];
	shotsPerWindow: number;
	range?: MetricRangeGuide;
	overlay: ChartOverlayState;
	onOverlayChange: (patch: Partial<ChartOverlayState>) => void;
};

export function buildRangeOverlayNodes(range: MetricRangeGuide, showBands: boolean, showLines: boolean): ReactNode[] {
	const nodes: ReactNode[] = [];
	if (showBands) {
		for (const band of range.bands) {
			nodes.push(
				<ReferenceArea
					key={`band-${band.level}-${band.lower}-${band.upper}`}
					y1={band.lower}
					y2={band.upper}
					fill={hexToRgba(band.fill, band.fillOpacity)}
					fillOpacity={1}
					stroke="none"
					ifOverflow="visible"
					isFront={false}
				/>,
			);
		}
	}
	if (showLines) {
		for (const line of range.lines) {
			if ((line.label ?? '').toLowerCase() === 'upper') {
				continue;
			}
			nodes.push(
				<ReferenceLine
					key={`line-${line.level}-${line.y}-${line.label ?? ''}`}
					y={line.y}
					stroke={line.stroke}
					strokeDasharray={line.strokeDasharray}
					strokeWidth={line.strokeWidth}
					strokeOpacity={line.strokeOpacity}
					ifOverflow="visible"
					isFront
				/>,
			);
		}
	}
	return nodes;
}

export function buildYTickHelperLineNodes(yTicks: number[]): ReactNode[] {
	const nodes: ReactNode[] = [];
	for (const y of yTicks) {
		if (!Number.isFinite(y) || y === 0) {
			continue;
		}
		nodes.push(
			<ReferenceLine
				key={`tick-helper-${y}`}
				y={y}
				stroke={LEVEL_COLOR.default}
				strokeDasharray="4 4"
				strokeWidth={1}
				strokeOpacity={0.55}
				ifOverflow="extendDomain"
				isFront
			/>,
		);
	}
	return nodes;
}

function hexToRgba(hex: string, alpha: number): string {
	const h = hex.replace('#', '');
	const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
	const n = Number.parseInt(full, 16);
	if (!Number.isFinite(n)) {
		return hex;
	}
	return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

const MetricChartPanel = memo(function MetricChartPanel({
	metric,
	points,
	shotsPerWindow,
	range,
	overlay,
	onOverlayChange,
}: MetricChartPanelProps) {
	const toolbar = chartToolbarFor(metric.key);
	const showBands = Boolean(range) && overlay.ranges;
	const configuredLines = range?.lines.filter(ln => (ln.label ?? '').toLowerCase() !== 'upper') ?? [];
	const hasConfiguredLines = configuredLines.length > 0;
	const showConfiguredLines = hasConfiguredLines && overlay.lines;
	const showTickHelpers = overlay.lines && !hasConfiguredLines;
	const showLines = showConfiguredLines || showTickHelpers;
	const showTrendline = overlay.trend;
	const showSeries = overlay.series;

	const { data, hasTrend } = useMemo(() => {
		const windowed = chartWindow(points, shotsPerWindow);
		if (!windowed.length) {
			return { data: showBands || showLines ? [{ epoch: 0, value: 0 }] : [], hasTrend: false };
		}
		const base = windowed.map(point => {
			const raw = metricValue(point, metric.key);
			return { epoch: point.epoch, value: raw != null && Number.isFinite(raw) ? raw : null };
		});
		if (!showTrendline) {
			return { data: base.map(row => ({ epoch: row.epoch, value: row.value ?? 0 })), hasTrend: false };
		}
		const samples = base.filter((row): row is { epoch: number; value: number } => row.value != null);
		const trendYs = emaTrendValues(samples, TREND_HALF_LIFE_EPOCHS);
		if (!trendYs) {
			return { data: base.map(row => ({ epoch: row.epoch, value: row.value ?? 0 })), hasTrend: false };
		}
		const trendByEpoch = new Map<number, number>();
		for (let i = 0; i < samples.length; i++) {
			trendByEpoch.set(samples[i]!.epoch, trendYs[i]!);
		}
		return {
			data: base.map(row => ({
				epoch: row.epoch,
				value: row.value ?? 0,
				trend: trendByEpoch.has(row.epoch) ? trendByEpoch.get(row.epoch)! : null,
			})),
			hasTrend: true,
		};
	}, [points, shotsPerWindow, metric.key, showBands, showLines, showTrendline]);

	const xDomain = useMemo(() => chartXDomain(points, shotsPerWindow), [points, shotsPerWindow]);

	const yDomain = useMemo((): [number, number] => {
		const series: number[] = [];
		for (const row of data) {
			if (showSeries && Number.isFinite(row.value)) {
				series.push(row.value);
			}
			if (hasTrend && 'trend' in row && typeof row.trend === 'number' && Number.isFinite(row.trend)) {
				series.push(row.trend);
			}
		}
		if (metric.key === 'qber') {
			const abort = typeof metric.technical_range?.abort_threshold === 'number'
				? metric.technical_range.abort_threshold
				: range?.domainUpper;
			return yDomainForPositiveValues(series, { minUpper: abortMinUpper(abort), maxUpper: 1 });
		}
		const dom = yDomainForSeries(series);
		if (dom[1] === 'auto') {
			return [0, 1];
		}
		return dom as [number, number];
	}, [data, hasTrend, showSeries, metric.key, metric.technical_range?.abort_threshold, range?.domainUpper]);

	const yTicks = useMemo(() => yTicksForDomain(yDomain), [yDomain]);
	const yAxisTitle = metric.unit?.trim() ? metric.unit : metric.label.length > 18 ? metric.key : metric.label;
	const formatYTick = (v: number) => formatMetricAxisTick(v, metric.key, yDomain[1]);

	const overlays = useMemo(() => {
		const nodes: ReactNode[] = [];
		if (range && (showBands || showConfiguredLines)) {
			nodes.push(...buildRangeOverlayNodes(range, showBands, showConfiguredLines));
		}
		if (showTickHelpers) {
			nodes.push(...buildYTickHelperLineNodes(yTicks));
		}
		return nodes;
	}, [range, showBands, showConfiguredLines, showTickHelpers, yTicks]);

	const showLegend = showSeries || hasTrend || showBands || showConfiguredLines || showTickHelpers;

	return (
		<Card className="flex h-full min-w-0 flex-col p-4">
			<Card.Header className="min-h-[5.25rem] shrink-0 pb-2">
				<div className="flex min-w-0 items-start justify-between gap-3">
					<div className="min-w-0 flex-1">
						<div className="flex min-w-0 flex-wrap items-baseline gap-2">
							<Card.Title className="text-sm">
								{metric.label}
								{metric.unit ? ` (${metric.unit})` : ''}
							</Card.Title>
						</div>
						{showLegend ? (
							<div className="mt-1.5 flex flex-wrap gap-2 text-xs text-muted">
								{showSeries ? (
									<span className="inline-flex items-center gap-1">
										<span className="inline-block h-0 w-3 border-t-2" style={{ borderColor: SERIES_STROKE }} />
										{metric.label}
									</span>
								) : null}
								{hasTrend ? (
									<span className="inline-flex items-center gap-1">
										<span className="inline-block h-0 w-3 border-t-[3px]" style={{ borderColor: SERIES_STROKE }} />
										trend
									</span>
								) : null}
								{showBands && range
									? range.bands.map(band => (
										<span key={`lg-${band.level}-${band.lower}`} className="inline-flex items-center gap-1">
											<span className="inline-block size-2.5 rounded-sm" style={{ backgroundColor: band.fill, opacity: Math.max(band.fillOpacity, 0.45) }} />
											{band.label ?? band.level}
										</span>
									))
									: null}
								{showConfiguredLines && range
									? configuredLines.map(ln => (
										<span key={`ll-${ln.level}-${ln.y}`} className="inline-flex items-center gap-1">
											<span className="inline-block h-0 w-3 border-t-2 border-dashed" style={{ borderColor: ln.stroke }} />
											{ln.label ?? ln.level}
										</span>
									))
									: null}
								{showTickHelpers ? (
									<span className="inline-flex items-center gap-1">
										<span className="inline-block h-0 w-3 border-t border-dashed" style={{ borderColor: LEVEL_COLOR.default }} />
										guides
									</span>
								) : null}
							</div>
						) : null}
					</div>
					{toolbar ? (
						<ChartCardSettings metricKey={metric.key} config={toolbar} value={overlay} onChange={onOverlayChange} />
					) : null}
				</div>
			</Card.Header>
			<Card.Content className="mt-auto pt-0">
				<div className="flex min-w-0 items-stretch gap-1">
					<div className="relative w-5 shrink-0" aria-hidden>
						<span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-90 whitespace-nowrap text-xs text-muted">
							{yAxisTitle}
						</span>
					</div>
					<div className="min-w-0 flex-1">
						<MetricLineChart data={data} height={200} className="metric-range-chart">
							<MetricLineChart.Grid vertical={false} strokeDasharray="3 3" stroke="var(--separator)" strokeOpacity={0.55} />
							<MetricLineChart.XAxis
								dataKey="epoch"
								type="number"
								domain={xDomain}
								allowDataOverflow
								tick={AXIS_TICK}
								tickMargin={4}
								height={30}
								label={{ value: 'epoch', position: 'insideBottom', offset: -2, style: { fontSize: 11, fill: 'var(--muted)' } }}
							/>
							<MetricLineChart.YAxis
								width={48}
								domain={yDomain}
								ticks={yTicks}
								allowDataOverflow
								tick={AXIS_TICK}
								tickMargin={4}
								tickFormatter={formatYTick}
							/>
							{overlays}
							{hasTrend ? (
								<MetricLineChart.Line dataKey="trend" name="Trend" type="monotone" stroke={SERIES_STROKE} strokeWidth={2.5} connectNulls {...LIVE_CHART_LINE_PROPS} />
							) : null}
							{showSeries ? (
								<MetricLineChart.Line dataKey="value" name={metric.label} type="monotone" stroke={SERIES_STROKE} strokeWidth={1} {...LIVE_CHART_LINE_PROPS} />
							) : null}
							<MetricLineChart.Tooltip
								isAnimationActive={false}
								formatter={(value: number, name: string) => [formatMetricAxisTick(Number(value), metric.key, yDomain[1]), name]}
							/>
						</MetricLineChart>
					</div>
				</div>
			</Card.Content>
		</Card>
	);
});

function formatMetricAxisTick(v: number, metricKey: string, domainHi: number): string {
	const n = Number(v);
	if (!Number.isFinite(n)) {
		return '';
	}
	if (n === 0) {
		return '0';
	}
	if (metricKey === 'qber') {
		return n.toFixed(2);
	}
	const a = Math.abs(n);
	const scale = Math.max(Math.abs(domainHi), a);
	if (scale >= 1000) {
		return Math.round(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
	}
	if (scale >= 100) {
		return Number.isInteger(n) || Math.abs(n - Math.round(n)) < 1e-6 ? String(Math.round(n)) : n.toFixed(1);
	}
	if (scale >= 10) {
		return trimFixed(n, 1);
	}
	if (scale >= 1) {
		return trimFixed(n, 2);
	}
	if (scale >= 0.1) {
		return trimFixed(n, 3);
	}
	if (scale >= 0.01) {
		return trimFixed(n, 4);
	}
	return trimFixed(n, 5);
}

function trimFixed(n: number, decimals: number): string {
	const s = n.toFixed(decimals);
	if (!s.includes('.')) {
		return s;
	}
	return s.replace(/\.?0+$/, '') || '0';
}

type MetricChartsProps = {
	points: DataPoint[];
	catalog: MetricCatalogEntry[];
	selected: Set<string>;
	chartColumns: ChartColumnCount;
	shotsPerWindow: number;
	chartOverlayByMetric: Record<string, Partial<ChartOverlayState>>;
	onOverlayChange: (metricKey: string, patch: Partial<ChartOverlayState>) => void;
};

export function MetricCharts(props: MetricChartsProps): JSX.Element {
	const plotted = useMemo(
		() => props.catalog.filter(metric => props.selected.has(metric.key)),
		[props.catalog, props.selected],
	);

	if (!plotted.length) {
		return <Card className="p-6 text-sm text-muted">Select at least one metric to plot.</Card>;
	}

	return (
		<div className={`grid gap-4 ${CHART_GRID_CLASS[props.chartColumns]}`}>
			{plotted.map(metric => (
				<MetricChartPanel
					key={metric.key}
					metric={metric}
					points={props.points}
					shotsPerWindow={props.shotsPerWindow}
					range={rangeGuideFromCatalog(metric.technical_range, metric.key)}
					overlay={resolveChartOverlay(props.chartOverlayByMetric[metric.key], metric.key)}
					onOverlayChange={patch => props.onOverlayChange(metric.key, patch)}
				/>
			))}
		</div>
	);
}
