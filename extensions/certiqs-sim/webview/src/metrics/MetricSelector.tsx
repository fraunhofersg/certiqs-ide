import { Eye, EyeSlash } from '@gravity-ui/icons';
import type { Key } from '@heroui/react';
import { ScrollShadow, ToggleButton, ToggleButtonGroup } from '@heroui/react';
import { useCallback } from 'react';
import type { MetricCatalogEntry } from '../../../src/apiTypes';
import { CHART_COLUMN_OPTIONS, type ChartColumnCount } from './columns';

type MetricSelectorProps = {
	catalog: MetricCatalogEntry[];
	selected: Set<string>;
	onSelectedChange: (next: Set<string>) => void;
	chartColumns: ChartColumnCount;
	onChartColumnsChange: (cols: ChartColumnCount) => void;
};

export function MetricSelector(props: MetricSelectorProps): JSX.Element | null {
	const onSelectionChange = useCallback((keys: Set<Key>) => {
		const next = new Set<string>();
		keys.forEach(key => next.add(String(key)));
		props.onSelectedChange(next);
	}, [props]);

	const onColumnsChange = useCallback((keys: Set<Key>) => {
		const picked = [...keys][0];
		if (picked == null) {
			return;
		}
		const cols = Number(picked) as ChartColumnCount;
		if (!CHART_COLUMN_OPTIONS.includes(cols)) {
			return;
		}
		props.onChartColumnsChange(cols);
	}, [props]);

	if (!props.catalog.length) {
		return null;
	}

	return (
		<div className="flex flex-wrap items-center gap-3 rounded-md border border-separator bg-surface px-3 py-2">
			<span className="shrink-0 text-xs font-medium uppercase tracking-wide text-muted">Plots</span>
			<ScrollShadow orientation="horizontal" hideScrollBar className="min-w-0 flex-1">
				<ToggleButtonGroup
					isDetached
					selectionMode="multiple"
					size="sm"
					aria-label="Plotted metrics"
					selectedKeys={props.selected}
					onSelectionChange={onSelectionChange}
					className="w-max flex-nowrap"
				>
					{props.catalog.map(metric => (
						<ToggleButton key={metric.key} id={metric.key} aria-label={metric.label} className="shrink-0">
							{({ isSelected }) => (
								<>
									{isSelected ? <Eye className="size-3.5" /> : <EyeSlash className="size-3.5" />}
									{metric.label}
								</>
							)}
						</ToggleButton>
					))}
				</ToggleButtonGroup>
			</ScrollShadow>
			<div className="flex shrink-0 items-center gap-2 border-l border-separator pl-3">
				<span className="text-[11px] uppercase tracking-wide text-muted">Cols</span>
				<ToggleButtonGroup
					isDetached
					selectionMode="single"
					size="sm"
					aria-label="Chart grid columns"
					selectedKeys={new Set([String(props.chartColumns)])}
					onSelectionChange={onColumnsChange}
					className="w-max flex-nowrap"
				>
					{CHART_COLUMN_OPTIONS.map(n => (
						<ToggleButton key={n} id={String(n)} aria-label={`${n} columns`} className="min-w-8">
							{n}
						</ToggleButton>
					))}
				</ToggleButtonGroup>
			</div>
			<span className="shrink-0 text-[11px] tabular-nums text-muted">{props.selected.size}/{props.catalog.length}</span>
		</div>
	);
}
