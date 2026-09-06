import { Button, Card, Chip, Spinner } from '@heroui/react';
import { useEffect, useState } from 'react';
import type { BootstrapSnapshot, DataPoint, MetricCatalogEntry, RunStatus, StreamMessage } from '../../src/apiTypes';
import { PROCESS_LABELS, type SimState } from '../../src/protocol';
import { rpc } from './hostRpc';
import { MetricCharts } from './metrics/MetricCharts';
import { MetricSelector } from './metrics/MetricSelector';
import type { ChartOverlayState } from './metrics/chart-card-settings';
import type { ChartColumnCount } from './metrics/columns';
import { onHostMessage, post } from './vscodeApi';

const KPI_KEYS = [
	{ key: 'qber', label: 'QBER' },
	{ key: 'sifted_key_bits', label: 'Sifted' },
	{ key: 'secret_key_bits', label: 'Secret' },
	{ key: 'key_rate_per_pulse', label: 'Rate / pulse' },
	{ key: 'coincidences', label: 'Coincidences' },
	{ key: 'selftest_alarm', label: 'Self-test' },
] as const;

export function Dashboard(): JSX.Element {
	const [state, setState] = useState<SimState | undefined>();
	const [boot, setBoot] = useState<BootstrapSnapshot | undefined>();
	const [points, setPoints] = useState<DataPoint[]>([]);
	const [catalog, setCatalog] = useState<MetricCatalogEntry[]>([]);
	const [status, setStatus] = useState<RunStatus | null>(null);
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [chartColumns, setChartColumns] = useState<ChartColumnCount>(2);
	const [chartOverlayByMetric, setChartOverlayByMetric] = useState<Record<string, Partial<ChartOverlayState>>>({});
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setState(message.payload);
			}
			if (message.type === 'bootstrap') {
				applyBootstrap(message.payload);
			}
			if (message.type === 'stream') {
				for (const frame of message.frames) {
					applyFrame(frame);
				}
			}
			if (message.type === 'rpcResult' && message.result && typeof message.result === 'object' && 'catalog' in (message.result as object) && 'points' in (message.result as object)) {
				applyBootstrap(message.result as BootstrapSnapshot);
			}
		});
		post({ type: 'ready' });
		void rpc<BootstrapSnapshot>('getBootstrap').then(applyBootstrap).finally(() => setLoading(false));
		return dispose;
	}, []);

	function applyBootstrap(payload: BootstrapSnapshot): void {
		setBoot(payload);
		setCatalog(payload.catalog);
		setPoints(payload.points);
		setStatus(payload.status);
		setSelected(current => {
			if (current.size) {
				return current;
			}
			return new Set(payload.catalog.filter(item => item.default_plot).map(item => item.key));
		});
	}

	function applyFrame(frame: StreamMessage): void {
		if (frame.type === 'catalog' && Array.isArray(frame.data)) {
			const next = frame.data as MetricCatalogEntry[];
			setCatalog(next);
			setSelected(current => current.size ? current : new Set(next.filter(item => item.default_plot).map(item => item.key)));
		}
		if (frame.type === 'status' && frame.data && typeof frame.data === 'object') {
			setStatus(frame.data as RunStatus);
		}
		if (frame.type === 'history' && Array.isArray(frame.data)) {
			setPoints(frame.data as DataPoint[]);
		}
		if (frame.type === 'datapoint' && frame.data && typeof frame.data === 'object') {
			const point = frame.data as DataPoint;
			setPoints(current => [...current.slice(-499), point]);
			setStatus(current => current ? { ...current, epoch: point.epoch, last_point: point } : current);
		}
	}

	const last = points.at(-1) ?? status?.last_point;
	const alarm = Number(last?.metrics.selftest_alarm ?? 0) >= 1;
	const shotsPerWindow = status?.shots_per_window ?? status?.current_settings?.shots_per_window ?? boot?.meta?.default_shots_per_window ?? state?.shotsPerWindow ?? 100_000;

	if (loading) {
		return (
			<div className="flex h-full items-center justify-center">
				<Spinner size="lg" />
			</div>
		);
	}

	return (
		<div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-5">
			<header className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<p className="text-xs font-semibold tracking-wide text-accent">Dashboard</p>
					<h1 className="text-xl font-semibold">Live twin metrics</h1>
					<p className="text-xs text-muted">Simulated results · run {status?.run_id ?? '—'} · {boot?.configName ?? state?.configName}</p>
				</div>
				<div className="flex flex-wrap gap-1.5">
					<Chip size="sm" variant="soft">{state?.api === 'ready' ? 'API ready' : 'API not ready'}</Chip>
					<Chip size="sm" variant="soft">{status?.status ?? 'idle'}</Chip>
					<Chip size="sm" variant="soft">epoch {status?.epoch ?? last?.epoch ?? 0}</Chip>
					{PROCESS_LABELS.map(label => <Chip key={label} size="sm" variant="soft">{label}</Chip>)}
					<Button size="sm" variant="ghost" onPress={() => post({ type: 'showMonitor' })}>Monitor</Button>
					<Button size="sm" variant="ghost" onPress={() => post({ type: 'showDebug' })}>Debug</Button>
					<Button size="sm" variant="ghost" onPress={() => post({ type: 'showPrompt' })}>Prompt</Button>
				</div>
			</header>

			{alarm ? (
				<Card className="border border-danger p-3 text-sm text-danger">Self-test alarm on the latest epoch. See Problems and Forensics output.</Card>
			) : null}

			<div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
				{KPI_KEYS.map(item => (
					<Card key={item.key} className="p-3">
						<p className="text-[11px] text-muted">{item.label}</p>
						<p className="text-lg font-semibold tabular-nums">{formatValue(last?.metrics[item.key])}</p>
					</Card>
				))}
			</div>

			<MetricSelector
				catalog={catalog}
				selected={selected}
				onSelectedChange={setSelected}
				chartColumns={chartColumns}
				onChartColumnsChange={setChartColumns}
			/>

			<MetricCharts
				points={points}
				catalog={catalog}
				selected={selected}
				chartColumns={chartColumns}
				shotsPerWindow={shotsPerWindow}
				chartOverlayByMetric={chartOverlayByMetric}
				onOverlayChange={(metricKey, patch) => setChartOverlayByMetric(current => ({
					...current,
					[metricKey]: { ...current[metricKey], ...patch },
				}))}
			/>
		</div>
	);
}

function formatValue(value: number | null | undefined): string {
	if (value == null || Number.isNaN(value)) {
		return '—';
	}
	if (Math.abs(value) >= 100) {
		return value.toFixed(0);
	}
	if (Math.abs(value) >= 1) {
		return value.toFixed(3);
	}
	return value.toFixed(4);
}
