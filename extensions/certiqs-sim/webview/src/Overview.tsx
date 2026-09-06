import { Accordion, Button, Card, Chip } from '@heroui/react';
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

export function Overview(): JSX.Element {
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

	return (
		<div className="welcome mx-auto flex max-w-3xl flex-col gap-5 p-6">
			<header className="flex flex-col gap-2">
				<p className="text-xs font-semibold tracking-wide text-accent">certiqs Sim</p>
				<h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
				<p className="text-sm text-muted">
					Local BBM92 digital-twin control plane for certiqs IDE. Results are simulated.
					They are not a measurement and not a security or conformity statement.
				</p>
				<div className="flex flex-wrap gap-1.5">
					<Chip size="sm" variant="soft">{apiLabel(state.api)}</Chip>
					{state.status ? <Chip size="sm" variant="soft">{state.status.status}</Chip> : null}
					<Chip size="sm" variant="soft">{state.configName}</Chip>
					{state.labels.map(label => (
						<Chip key={label} size="sm" variant="soft">{label}</Chip>
					))}
				</div>
			</header>

			<div className="flex flex-wrap gap-2">
				<Button size="sm" onPress={() => post({ type: 'focusRunControl' })}>Open Run Control</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'openDashboard' })}>Dashboard</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'openSystem' })}>System</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'startApi' })}>Start API</Button>
				<Button size="sm" variant="ghost" onPress={() => post({ type: 'showLog' })}>Show Sim Log</Button>
				<Button size="sm" variant="ghost" onPress={() => post({ type: 'showPrompt' })}>Prompt Terminal</Button>
			</div>

			<Card className="p-5">
				<Card.Header className="pb-3">
					<Card.Title>What this extension does</Card.Title>
					<Card.Description>
						Run Control stays in the activity bar. Dashboard and System open as editor tabs.
						Logs and the prompt terminal use certiqs IDE Output and Terminal.
					</Card.Description>
				</Card.Header>
				<Card.Content className="flex flex-col gap-3 text-sm">
					<p>
						The extension host owns a local Python process and talks to its
						{' '}<code className="font-mono text-xs">/api/v1</code> contract on
						{' '}<code className="font-mono text-xs">127.0.0.1:{state.port}</code>.
						These pages never open that connection — they only post typed messages.
					</p>
					<ul className="list-disc space-y-1 pl-5 text-muted">
						<li>Overview — status, origin labels, and entry points</li>
						<li>System — configuration, topology, and component inventory</li>
						<li>Dashboard — live KPIs and metric charts</li>
						<li>Output / Problems / Terminal — process, monitor, forensics, debug, prompt</li>
					</ul>
				</Card.Content>
			</Card>

			<Accordion allowsMultipleExpanded className="w-full" defaultExpandedKeys={['start']} hideSeparator>
				<Accordion.Item id="start">
					<Accordion.Heading>
						<Accordion.Trigger>
							Start a simulation
							<Accordion.Indicator />
						</Accordion.Trigger>
					</Accordion.Heading>
					<Accordion.Panel>
						<Accordion.Body>
							<ol className="list-decimal space-y-2 pl-5 text-sm">
								<li>Click the beaker. Run Control opens on the left; this page opens here.</li>
								<li>Open System and pick a bundled configuration.</li>
								<li>Wait until Run Control shows <strong>API ready</strong>.</li>
								<li>Press <strong>Start simulation</strong>, then open Dashboard for charts.</li>
								<li>Watch Output, Problems, and the Prompt terminal for logs — not an in-page console.</li>
							</ol>
							<p className="mt-3 text-sm text-muted">{state.notice}</p>
						</Accordion.Body>
					</Accordion.Panel>
				</Accordion.Item>
			</Accordion>
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
