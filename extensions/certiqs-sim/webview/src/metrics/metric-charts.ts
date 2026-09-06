export type ChartCardToolbarConfig = {
	ranges?: boolean;
	lines?: boolean;
	trend?: boolean;
	series?: boolean;
};

export type ChartOverlayDefaults = {
	ranges: boolean;
	lines: boolean;
	trend: boolean;
	series: boolean;
};

export const DEFAULT_CHART_OVERLAY: ChartOverlayDefaults = {
	ranges: true,
	lines: false,
	trend: false,
	series: true,
};

export const METRIC_CHART_TOOLBAR: Record<string, ChartCardToolbarConfig> = {
	qber: { ranges: true, lines: true, trend: true, series: true },
	secret_key_total: { ranges: false, lines: true, trend: false, series: true },
	secret_key_bits: { ranges: true, lines: false, trend: false, series: true },
	sifted_key_bits: { ranges: true, lines: false, trend: false, series: true },
	secret_fraction: { ranges: true, lines: false, trend: false, series: true },
	key_rate_per_pulse: { ranges: true, lines: false, trend: false, series: true },
	coincidences: { ranges: true, lines: false, trend: false, series: true },
	bob_detection_rate: { ranges: true, lines: false, trend: false, series: true },
	eve_knowledge_fraction: { ranges: true, lines: false, trend: false, series: true },
	attack_success_prob: { ranges: true, lines: false, trend: false, series: true },
	pp_secure_key_bits: { ranges: true, lines: false, trend: false, series: true },
	pp_secure_key_total: { ranges: true, lines: false, trend: false, series: true },
	pp_ec_leakage_bits: { ranges: true, lines: false, trend: false, series: true },
	selftest_alarm: { ranges: true, lines: false, trend: false, series: true },
};
