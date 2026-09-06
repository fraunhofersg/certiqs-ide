import { Button, Chip } from '@heroui/react';
import { openPage } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { post } from '../vscodeApi';

const LINKS = [
	{ surface: 'hub' as const, label: 'Hub' },
	{ surface: 'systems' as const, label: 'Systems' },
	{ surface: 'wizard' as const, label: 'New system' },
	{ surface: 'applicability' as const, label: 'Applicability' },
	{ surface: 'search' as const, label: 'Search' },
	{ surface: 'vulnerabilities' as const, label: 'Attacks' },
	{ surface: 'eas' as const, label: 'Evaluation activities' },
	{ surface: 'countermeasures' as const, label: 'Countermeasures' },
	{ surface: 'documents' as const, label: 'Documents' },
];

export function Sidebar(): JSX.Element {
	const state = useQdbState();
	return (
		<div className="flex flex-col gap-3 p-3">
			<header className="px-1">
				<p className="text-xs font-semibold tracking-wide">QDB Explorer</p>
				<p className="qdb-muted">127.0.0.1:{state.port}</p>
			</header>
			<div className="qdb-row px-1">
				<Chip size="sm" variant="soft">{apiLabel(state.api)}</Chip>
				{state.isAdmin ? <Chip size="sm" variant="soft">admin</Chip> : null}
			</div>
			{state.apiError ? <p className="qdb-error px-1">{state.apiError}</p> : null}
			<div className="flex flex-col gap-1.5">
				{LINKS.map(link => (
					<Button key={link.surface} size="sm" variant="outline" onPress={() => openPage(link.surface, state.selectedSystemId)}>
						{link.label}
					</Button>
				))}
			</div>
			<div className="qdb-row">
				<Button size="sm" variant="primary" onPress={() => post({ type: 'startApi' })}>Start API</Button>
				<Button size="sm" variant="outline" onPress={() => post({ type: 'stopApi' })}>Stop</Button>
				<Button size="sm" variant="ghost" onPress={() => post({ type: 'showLog' })}>Log</Button>
			</div>
		</div>
	);
}

function apiLabel(api: string): string {
	if (api === 'ready') {
		return 'API ready';
	}
	if (api === 'starting') {
		return 'Starting';
	}
	if (api === 'error') {
		return 'API error';
	}
	return 'API stopped';
}
