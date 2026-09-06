import { Button, Card, Chip, Input, Label, Spinner, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import { PROCESS_LABELS, type SimState } from '../../src/protocol';
import { onHostMessage, post } from './vscodeApi';

const INITIAL: SimState = {
	api: 'stopped',
	pythonPath: 'python3',
	port: 8011,
	configs: [],
	configName: 'bbm92-minimal',
	shotsPerWindow: 100_000,
	lifecycle: 'idle',
	labels: PROCESS_LABELS,
	notice: 'This panel talks to a local certiqsSim control plane. Results are simulated and are not a measurement.',
};

export function RunControl(): JSX.Element {
	const [state, setState] = useState<SimState>(INITIAL);

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setState(message.payload);
			}
		});
		post({ type: 'ready' });
		return dispose;
	}, []);

	const status = state.status?.status ?? 'idle';
	const running = status === 'running' || status === 'stopping' || status === 'initialized';
	const starting = state.lifecycle === 'starting';
	const stopping = state.lifecycle === 'stopping' || status === 'stopping';
	const busy = starting || stopping;
	const controlsLocked = running || busy || state.api !== 'ready';
	const epoch = state.status?.epoch ?? 0;
	const settingsVer = state.status?.settings_version;
	const apiReady = state.api === 'ready';

	return (
		<div className="flex flex-col gap-3 p-3">
			<header className="px-1">
				<p className="text-xs font-semibold tracking-wide text-foreground">Run Control</p>
				<p className="text-muted text-xs">Local certiqsSim · 127.0.0.1:{state.port}</p>
			</header>

			<div className="flex flex-wrap items-center gap-1.5 px-1">
				<Chip size="sm" variant="soft">{apiLabel(state.api)}</Chip>
				{state.status ? (
					<Chip size="sm" variant="soft">{state.status.status}</Chip>
				) : null}
			</div>

			<Card className="p-4">
				<Card.Header className="pb-3">
					<Card.Title>Run control</Card.Title>
					<Card.Description>
						{state.configName
							? `Active configuration: ${state.configName}. Bundled YAML only — this is not a measurement.`
							: 'No configuration selected. Choose a bundled YAML set to enable simulation runs.'}
					</Card.Description>
				</Card.Header>
				<Card.Content className="flex flex-col gap-4">
					<div className="flex flex-col gap-1.5">
						<Label htmlFor="certiqs-sim-config">Configuration</Label>
						<select
							id="certiqs-sim-config"
							className="rounded-md border border-separator bg-surface px-3 py-2 font-mono text-sm"
							value={state.configName}
							disabled={controlsLocked || !state.configs.length}
							onChange={event => post({ type: 'setConfig', configName: event.target.value })}
						>
							{(state.configs.length ? state.configs : [state.configName]).map(name => (
								<option key={name} value={name}>{name}</option>
							))}
						</select>
					</div>

					<div className="grid grid-cols-2 gap-3">
						<TextField
							name="shots"
							type="number"
							value={String(state.shotsPerWindow)}
							isDisabled={controlsLocked}
							onChange={value => post({ type: 'setShots', shotsPerWindow: Number(value) || 100_000 })}
						>
							<Label>Shots per epoch</Label>
							<Input min={1000} step={1000} className="tabular-nums" />
						</TextField>
						<div className="flex flex-col gap-1.5">
							<Label>Epoch</Label>
							<div
								className="rounded-md border border-separator bg-surface px-3 py-2 text-sm font-semibold tabular-nums"
								aria-live="polite"
							>
								{epoch}
								<span className="ml-1.5 text-[11px] font-normal text-muted">
									v{settingsVer ?? '—'}
								</span>
							</div>
						</div>
					</div>

					<div className="flex flex-wrap items-center gap-2">
						<Button
							size="sm"
							isDisabled={controlsLocked || !state.configName}
							onPress={() => post({ type: 'startRun' })}
						>
							{starting ? (
								<>
									<Spinner size="sm" color="current" />
									Starting…
								</>
							) : (
								'Start simulation'
							)}
						</Button>
						<Button
							size="sm"
							variant="danger"
							isDisabled={!running || busy}
							onPress={() => post({ type: 'stopRun' })}
						>
							{stopping ? (
								<>
									<Spinner size="sm" color="current" />
									Stopping…
								</>
							) : (
								'Stop'
							)}
						</Button>
					</div>
					{stopping ? (
						<p className="text-xs text-muted">
							Finishing the current epoch, then shutting down…
						</p>
					) : null}
					{state.status?.error ? (
						<p className="text-xs text-danger">{state.status.error}</p>
					) : null}
				</Card.Content>
			</Card>

			<div className="flex flex-wrap gap-2 px-1">
				<Button size="sm" variant="outline" onPress={() => post({ type: 'openWelcome' })}>
					Overview
				</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'openDashboard' })}>
					Dashboard
				</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'openSystem' })}>
					System
				</Button>
				{apiReady ? (
					<Button size="sm" variant="outline" onPress={() => post({ type: 'stopApi' })}>
						Stop API
					</Button>
				) : (
					<Button size="sm" variant="outline" isDisabled={state.api === 'starting'} onPress={() => post({ type: 'startApi' })}>
						{state.api === 'starting' ? 'Starting API…' : 'Start API'}
					</Button>
				)}
				<Button size="sm" variant="ghost" onPress={() => post({ type: 'refresh' })}>
					Refresh
				</Button>
			</div>

			{state.apiError ? (
				<p className="px-1 text-xs text-danger">{state.apiError}</p>
			) : null}
			{state.api === 'error' || state.api === 'stopped' ? (
				<p className="px-1 text-xs text-muted">
					If the API never becomes ready, install control-plane deps with
					{' '}
					<code className="font-mono">python3 -m pip install -r extensions/certiqs-sim/python/requirements-ide.txt</code>
					. NetSquid is optional and only required to start a run.
				</p>
			) : null}

			<p className="px-1 text-xs text-muted">{state.notice}</p>
			<div className="flex flex-wrap gap-1.5 px-1">
				{state.labels.map(label => (
					<Chip key={label} size="sm" variant="soft">
						{label}
					</Chip>
				))}
			</div>
		</div>
	);
}

function apiLabel(api: SimState['api']): string {
	switch (api) {
		case 'ready':
			return 'API ready';
		case 'starting':
			return 'API starting';
		case 'error':
			return 'API error';
		default:
			return 'API stopped';
	}
}
