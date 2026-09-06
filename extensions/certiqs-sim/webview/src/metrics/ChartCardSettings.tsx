import { Switch } from '@heroui/react';
import type { ChartCardToolbarConfig, ChartOverlayState } from './chart-card-settings';

type ChartCardSettingsProps = {
	metricKey: string;
	config: ChartCardToolbarConfig;
	value: ChartOverlayState;
	onChange: (patch: Partial<ChartOverlayState>) => void;
};

function TinySwitch(props: { label: string; selected: boolean; onChange: (on: boolean) => void }) {
	return (
		<Switch size="sm" isSelected={props.selected} onChange={props.onChange} aria-label={props.label} className="gap-1">
			<Switch.Content className="gap-1">
				<Switch.Control className="h-3.5 w-6 min-w-6">
					<Switch.Thumb className="size-2.5" />
				</Switch.Control>
				<span className="text-[10px] leading-none text-muted">{props.label}</span>
			</Switch.Content>
		</Switch>
	);
}

export function ChartCardSettings({ metricKey, config, value, onChange }: ChartCardSettingsProps) {
	const items: Array<{ key: keyof ChartOverlayState; label: string; show?: boolean }> = [
		{ key: 'ranges', label: 'Ranges', show: config.ranges },
		{ key: 'lines', label: 'Lines', show: config.lines },
		{ key: 'trend', label: 'Trend', show: config.trend },
		{ key: 'series', label: 'Line', show: config.series },
	];
	const visible = items.filter(item => item.show);
	if (!visible.length) {
		return null;
	}
	return (
		<div className="flex shrink-0 flex-wrap items-center justify-end gap-x-2 gap-y-1" role="group" aria-label={`${metricKey} chart settings`}>
			{visible.map(item => (
				<TinySwitch
					key={item.key}
					label={item.label}
					selected={value[item.key]}
					onChange={on => onChange({ [item.key]: on })}
				/>
			))}
		</div>
	);
}
