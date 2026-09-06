export const CHART_COLUMN_OPTIONS = [2, 4, 6, 8] as const;
export type ChartColumnCount = (typeof CHART_COLUMN_OPTIONS)[number];
