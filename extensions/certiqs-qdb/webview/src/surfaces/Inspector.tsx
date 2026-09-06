import { Button, Card, Chip } from '@heroui/react';
import { useEffect, useState } from 'react';
import { api, openPage } from '../hostRpc';
import { useQdbState } from '../useQdbState';

type SystemRow = {
	id: number;
	name: string;
	manufacturer: string | null;
	toe_boundary?: string | null;
	encoding_name?: string | null;
	architecture_name?: string | null;
};

export function Inspector(): JSX.Element {
	const state = useQdbState();
	const [system, setSystem] = useState<SystemRow | undefined>();
	const [error, setError] = useState('');

	useEffect(() => {
		if (state.api !== 'ready' || !state.selectedSystemId) {
			setSystem(undefined);
			return;
		}
		let cancelled = false;
		api<SystemRow>('GET', `/internal/systems/${state.selectedSystemId}`)
			.then(row => {
				if (!cancelled) {
					setSystem(row);
					setError('');
				}
			})
			.catch(err => {
				if (!cancelled) {
					setError((err as Error).message);
				}
			});
		return () => {
			cancelled = true;
		};
	}, [state.api, state.selectedSystemId]);

	return (
		<div className="flex flex-col gap-3 p-3">
			<header className="px-1">
				<p className="text-xs font-semibold tracking-wide">QDB Inspector</p>
				<p className="qdb-muted">{state.isAdmin ? 'Admin principal' : `user ${state.userId.slice(0, 8)}`}</p>
			</header>
			<div className="qdb-row px-1">
				<Chip size="sm" variant="soft">{state.api}</Chip>
			</div>
			{!state.selectedSystemId ? (
				<p className="qdb-muted px-1">Select a system from the list to inspect it here.</p>
			) : error ? (
				<p className="qdb-error px-1">{error}</p>
			) : system ? (
				<Card className="p-3">
					<Card.Header className="pb-2">
						<Card.Title>{String(system.name ?? `System ${state.selectedSystemId}`)}</Card.Title>
						<Card.Description>{String(system.manufacturer ?? 'No manufacturer')}</Card.Description>
					</Card.Header>
					<Card.Content className="flex flex-col gap-2 text-xs">
						<p>TOE: {String(system.toe_boundary ?? '—')}</p>
						<p>Encoding: {String(system.encoding_name ?? '—')}</p>
						<p>Architecture: {String(system.architecture_name ?? '—')}</p>
						<div className="qdb-row">
							<Button size="sm" variant="primary" onPress={() => openPage('system', state.selectedSystemId)}>Detail</Button>
							<Button size="sm" variant="outline" onPress={() => openPage('applicability', state.selectedSystemId)}>Applicability</Button>
						</div>
					</Card.Content>
				</Card>
			) : (
				<p className="qdb-muted px-1">Loading system {state.selectedSystemId}…</p>
			)}
		</div>
	);
}
