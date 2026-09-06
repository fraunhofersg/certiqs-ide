import { Button, Input, Label, TextField } from '@heroui/react';
import { useEffect, useState } from 'react';
import { api, openPage, rpc } from '../hostRpc';
import { useQdbState } from '../useQdbState';
import { ErrorText, Page } from './Page';

type Protocol = { id: number; protocol_family_id: number; name: string };
type ModuleType = { id: number; name: string };
type ComponentType = { id: number; name: string; module_type_id: number | null };
type Defaults = Record<string, number>;

const PROFILE_FIELDS = [
	{ key: 'doubleClickHandling', label: 'Double-click handling' },
	{ key: 'basisChoice', label: 'Basis choice' },
	{ key: 'deployment', label: 'Deployment' },
	{ key: 'opticalPathDirection', label: 'Optical path direction' },
	{ key: 'localOscillatorType', label: 'Local oscillator type' },
	{ key: 'phaseRandomisationMethod', label: 'Phase randomisation' },
	{ key: 'reconciliationAlgorithm', label: 'Reconciliation algorithm' },
] as const;

export function Wizard(): JSX.Element {
	const state = useQdbState();
	const [name, setName] = useState('');
	const [manufacturer, setManufacturer] = useState('');
	const [toeBoundary, setToeBoundary] = useState('');
	const [protocols, setProtocols] = useState<Protocol[]>([]);
	const [selectedProtocol, setSelectedProtocol] = useState<number | ''>('');
	const [moduleTypes, setModuleTypes] = useState<ModuleType[]>([]);
	const [componentTypes, setComponentTypes] = useState<ComponentType[]>([]);
	const [defaults, setDefaults] = useState<Defaults>({});
	const [profile, setProfile] = useState<Record<string, string>>({});
	const [error, setError] = useState('');
	const [busy, setBusy] = useState(false);

	useEffect(() => {
		if (state.api !== 'ready') {
			return;
		}
		void Promise.all([
			api<Protocol[]>('GET', '/internal/catalog/protocols'),
			api<ModuleType[]>('GET', '/internal/catalog/module-types'),
			api<ComponentType[]>('GET', '/internal/catalog/component-types'),
			api<Defaults>('GET', '/internal/components/defaults'),
		]).then(([p, m, c, d]) => {
			setProtocols(p);
			setModuleTypes(m);
			setComponentTypes(c);
			setDefaults(d);
		}).catch(err => setError((err as Error).message));
	}, [state.api]);

	async function submit(): Promise<void> {
		setBusy(true);
		setError('');
		try {
			const tx = moduleTypes.find(item => item.name === 'TX' || item.name === 'TRANSMITTER');
			const rx = moduleTypes.find(item => item.name === 'RX' || item.name === 'RECEIVER');
			const modules = [tx, rx].filter(Boolean).map(moduleType => {
				const types = componentTypes.filter(item => item.module_type_id === moduleType!.id);
				return {
					moduleTypeId: moduleType!.id,
					name: moduleType!.name,
					firmwareRevision: '',
					components: types.slice(0, 4).map((type, index) => ({
						componentTypeId: type.id,
						componentId: defaults[String(type.id)] ?? defaults[type.id as unknown as string],
						name: type.name,
						instanceName: `${moduleType!.name.toLowerCase()}-${type.name.toLowerCase().replace(/\s+/g, '-')}-${index + 1}`,
						domain: 'quantum',
						parameters: [],
					})).filter(item => item.componentId),
				};
			});
			const created = await api<{ id: number }>('POST', '/internal/systems', {
				body: {
					name,
					manufacturer,
					toeBoundary,
					protocolIds: selectedProtocol ? [{ id: selectedProtocol, isPrimary: true }] : [],
					modules,
					connections: [],
					systemCountermeasures: [],
					systemPp: [],
					...profile,
				},
			});
			await rpc('setSelectedSystem', { systemId: created.id });
			openPage('system', created.id);
		} catch (err) {
			setError((err as Error).message);
		} finally {
			setBusy(false);
		}
	}

	return (
		<Page title="New system" subtitle="Start · Protocol · Profile · Modules. Domain step order still applies: protocol before components.">
			<ErrorText error={error} />
			<div className="grid gap-3 md:grid-cols-2">
				<TextField>
					<Label>Name</Label>
					<Input value={name} onChange={event => setName(event.target.value)} />
				</TextField>
				<TextField>
					<Label>Manufacturer</Label>
					<Input value={manufacturer} onChange={event => setManufacturer(event.target.value)} />
				</TextField>
				<TextField className="md:col-span-2">
					<Label>TOE boundary</Label>
					<Input value={toeBoundary} onChange={event => setToeBoundary(event.target.value)} />
				</TextField>
				<div className="flex flex-col gap-1.5">
					<Label>Primary protocol</Label>
					<select
						className="rounded-md border border-separator bg-surface px-3 py-2"
						value={selectedProtocol}
						onChange={event => setSelectedProtocol(event.target.value ? Number(event.target.value) : '')}
					>
						<option value="">Select protocol</option>
						{protocols.map(protocol => (
							<option key={protocol.id} value={protocol.id}>{protocol.name}</option>
						))}
					</select>
				</div>
			</div>
			<div className="grid gap-3 md:grid-cols-2">
				{PROFILE_FIELDS.map(field => (
					<TextField key={field.key}>
						<Label>{field.label}</Label>
						<Input
							value={profile[field.key] ?? ''}
							onChange={event => setProfile(current => ({ ...current, [field.key]: event.target.value }))}
						/>
					</TextField>
				))}
			</div>
			<p className="qdb-muted">TX/RX modules are seeded from catalogue defaults for the selected module types. Required-component rules still apply server-side.</p>
			<Button variant="primary" isDisabled={busy || !name || !selectedProtocol} onPress={() => void submit()}>
				{busy ? 'Creating…' : 'Create system'}
			</Button>
		</Page>
	);
}
