import type { MetricTechnicalRange } from '../../../src/apiTypes';

export type AssessmentLevel = 'success' | 'warning' | 'danger' | 'default';

export type StyledBand = {
	level: AssessmentLevel;
	lower: number;
	upper: number;
	label?: string;
	fill: string;
	fillOpacity: number;
};

export type StyledLine = {
	level: AssessmentLevel;
	y: number;
	label?: string;
	stroke: string;
	strokeOpacity: number;
	strokeDasharray: string;
	strokeWidth: number;
};

export type MetricRangeGuide = {
	label?: string;
	context?: string;
	bands: StyledBand[];
	lines: StyledLine[];
	domainLower: number;
	domainUpper: number;
};

/** Concrete hex for Recharts SVG — certiqs mint / warning / danger. */
export const LEVEL_COLOR: Record<AssessmentLevel, string> = {
	success: '#3ecf9a',
	warning: '#eab308',
	danger: '#f43f5e',
	default: '#94a3b8',
};

const BAND_OPACITY: Record<AssessmentLevel, number> = {
	success: 0.38,
	warning: 0.34,
	danger: 0.3,
	default: 0.22,
};

const LINE_OPACITY: Record<AssessmentLevel, number> = {
	success: 1,
	warning: 1,
	danger: 1,
	default: 0.9,
};

function normalizeLevel(level: string | undefined): AssessmentLevel {
	const l = (level || 'default').toLowerCase();
	if (l === 'success' || l === 'warning' || l === 'danger' || l === 'default') {
		return l;
	}
	if (l === 'error' || l === 'abort' || l === 'security') {
		return 'danger';
	}
	if (l === 'operating' || l === 'good') {
		return 'success';
	}
	return 'default';
}

export function rangeGuideFromCatalog(
	technical: MetricTechnicalRange | null | undefined,
	metricKey?: string,
): MetricRangeGuide | undefined {
	if (!technical) {
		return undefined;
	}

	const warnTh = typeof technical.warning_threshold === 'number' ? technical.warning_threshold : null;
	const abortTh = typeof technical.abort_threshold === 'number' ? technical.abort_threshold : null;
	const useQberBands = metricKey === 'qber' && warnTh != null && abortTh != null && abortTh > warnTh;

	let bands: StyledBand[] = [];
	let lines: StyledLine[] = [];

	if (useQberBands) {
		bands = [
			styleBand('success', 0, warnTh!, 'OK / below warning'),
			styleBand('warning', warnTh!, abortTh!, 'Warning → approach abort'),
			styleBand('danger', abortTh!, 1, 'Abort / above threshold'),
		];
		if (typeof technical.nominal === 'number') {
			lines.push(styleLine('success', technical.nominal, 'nominal'));
		}
		lines.push(styleLine('warning', warnTh!, 'warning'));
		lines.push(styleLine('danger', abortTh!, 'abort'));
	} else {
		bands = (technical.bands ?? [])
			.filter(b => Number.isFinite(b.lower) && Number.isFinite(b.upper) && b.upper > b.lower)
			.map(b => styleBand(normalizeLevel(b.level), b.lower, b.upper, b.label ?? undefined));
		lines = (technical.lines ?? [])
			.filter(ln => Number.isFinite(ln.y))
			.map(ln => styleLine(normalizeLevel(ln.level), ln.y, ln.label ?? undefined, ln.style));
		if (!bands.length && technical.lower != null && technical.upper != null) {
			bands.push(styleBand(normalizeLevel(technical.kind || 'success'), technical.lower, technical.upper, technical.label ?? undefined));
		}
	}

	if (!bands.length && !lines.length) {
		return undefined;
	}

	const ys = [...bands.flatMap(b => [b.lower, b.upper]), ...lines.map(ln => ln.y)];
	return {
		label: technical.label ?? undefined,
		context: technical.context ?? undefined,
		bands,
		lines,
		domainLower: Math.min(...ys, 0),
		domainUpper: useQberBands ? abortTh! : Math.max(...ys),
	};
}

function styleBand(level: AssessmentLevel, lower: number, upper: number, label?: string): StyledBand {
	return { level, lower, upper, label, fill: LEVEL_COLOR[level], fillOpacity: BAND_OPACITY[level] };
}

function styleLine(level: AssessmentLevel, y: number, label?: string, style?: string | null): StyledLine {
	const dashed = (style || 'dashed') !== 'solid';
	return {
		level,
		y,
		label,
		stroke: LEVEL_COLOR[level],
		strokeOpacity: LINE_OPACITY[level],
		strokeDasharray: dashed ? '6 4' : '0',
		strokeWidth: level === 'success' || level === 'danger' ? 1.25 : 1,
	};
}

export function niceCeil(value: number): number {
	if (!Number.isFinite(value) || value <= 0) {
		return 1;
	}
	const exp = Math.floor(Math.log10(value));
	const base = 10 ** exp;
	const mantissa = value / base;
	let nice: number;
	if (mantissa <= 1) {
		nice = 1;
	} else if (mantissa <= 2) {
		nice = 2;
	} else if (mantissa <= 5) {
		nice = 5;
	} else {
		nice = 10;
	}
	return nice * base;
}

export function nextNiceCeil(value: number): number {
	if (!Number.isFinite(value) || value <= 0) {
		return 1;
	}
	const atOrAbove = niceCeil(value);
	if (atOrAbove > value * (1 + 1e-12)) {
		return atOrAbove;
	}
	return niceCeil(atOrAbove * 1.01);
}

export function yDomainForPositiveValues(
	values: number[],
	opts?: { minUpper?: number | null; maxUpper?: number | null },
): [number, number] {
	const vals = values.filter(v => Number.isFinite(v));
	const dataHi = vals.length ? Math.max(...vals, 0) : 0;
	const minUpperRaw = opts?.minUpper != null && Number.isFinite(opts.minUpper) && opts.minUpper > 0 ? opts.minUpper : null;
	const needed = Math.max(dataHi, minUpperRaw ?? 0, 1e-9);
	let hi = nextNiceCeil(needed);
	if (needed >= hi * 0.92) {
		hi = nextNiceCeil(hi);
	}
	if (opts?.maxUpper != null && Number.isFinite(opts.maxUpper)) {
		hi = Math.min(Math.max(hi, needed), opts.maxUpper);
	}
	return [0, Math.max(hi, 1e-4)];
}

export function yTicksForDomain(domain: [number, number], maxTicks = 5): number[] {
	const [lo, hi] = domain;
	if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
		return [lo, hi];
	}
	const span = hi - lo;
	const step = niceCeil(span / Math.max(maxTicks - 1, 1));
	const ticks: number[] = [];
	for (let t = lo; t < hi - step * 1e-9; t += step) {
		ticks.push(Number(t.toPrecision(12)));
	}
	if (ticks[ticks.length - 1] !== hi) {
		ticks.push(hi);
	}
	return ticks;
}

export function yDomainForSeries(values: number[]): [number, number] | [number, 'auto'] {
	const vals = values.filter(v => Number.isFinite(v));
	if (!vals.length) {
		return [0, 'auto'];
	}
	const lo = Math.min(...vals);
	const hi = Math.max(...vals);
	if (lo >= 0) {
		return yDomainForPositiveValues(vals);
	}
	const mag = Math.max(Math.abs(lo), Math.abs(hi), 1e-9);
	const pad = nextNiceCeil(mag);
	return [-pad, pad];
}

export function abortMinUpper(abortThreshold: number | null | undefined, marginFraction = 0.15): number | null {
	if (abortThreshold == null || !Number.isFinite(abortThreshold) || abortThreshold <= 0) {
		return null;
	}
	return abortThreshold * (1 + marginFraction);
}

export function emaTrendValues(points: Array<{ epoch: number; value: number }>, halfLifeEpochs = 10): number[] | null {
	const usable = points.filter(p => Number.isFinite(p.epoch) && Number.isFinite(p.value));
	if (usable.length < 2) {
		return null;
	}
	const hl = Math.max(halfLifeEpochs, 1e-6);
	const out: number[] = new Array(usable.length);
	let ema = usable[0]!.value;
	out[0] = ema;
	for (let i = 1; i < usable.length; i++) {
		const dt = Math.max(usable[i]!.epoch - usable[i - 1]!.epoch, 1e-9);
		const alpha = 1 - Math.exp((-Math.LN2 * dt) / hl);
		ema = alpha * usable[i]!.value + (1 - alpha) * ema;
		out[i] = ema;
	}
	return out;
}
