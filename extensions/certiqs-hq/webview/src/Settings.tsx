import { CircleInfo, Flask, Gear } from '@gravity-ui/icons';
import { Button, Chip, FieldError, Input, Switch, TextField } from '@heroui/react';
import { useEffect, useMemo, useState } from 'react';
import type { InterpreterInfo, SettingsCatalog, SettingsField, SettingsSection, SettingsSourceState } from '../../src/settingsContract';
import { onHostMessage, post } from './vscodeApi';

type SectionRef = { sourceId: string; section: SettingsSection };

export function Settings(): JSX.Element {
	const [catalog, setCatalog] = useState<SettingsCatalog>({ sources: [] });
	const [drafts, setDrafts] = useState<Record<string, Record<string, string | number | boolean>>>({});
	const [secrets, setSecrets] = useState<Record<string, Record<string, string>>>({});
	const [active, setActive] = useState<string>('');

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'settings') {
				setCatalog(message.payload);
				setDrafts({});
				setSecrets({});
			}
		});
		post({ type: 'readySettings' });
		return dispose;
	}, []);

	const sections = useMemo(() => flatten(catalog.sources), [catalog.sources]);
	const current = sections.find(item => keyOf(item) === active) ?? sections[0];

	useEffect(() => {
		if (!active && sections[0]) {
			setActive(keyOf(sections[0]));
		}
	}, [active, sections]);

	const source = catalog.sources.find(item => item.id === current?.sourceId);

	const save = (clearSecrets?: string[]) => {
		if (!source) {
			return;
		}
		post({
			type: 'saveSettings',
			sourceId: source.id,
			values: { ...source.values, ...(drafts[source.id] ?? {}) },
			secrets: secrets[source.id],
			clearSecrets,
		});
	};

	return (
		<div className="settings-shell flex h-full min-h-full">
			<nav className="settings-nav flex w-[148px] shrink-0 flex-col gap-1 border-r border-separator px-2 py-3">
				<p className="mb-2 px-2 text-[11px] font-semibold tracking-wide text-foreground">certiqs Settings</p>
				{sections.map(item => (
					<NavItem
						key={keyOf(item)}
						label={item.section.title}
						icon={item.section.icon}
						active={keyOf(item) === keyOf(current)}
						onSelect={() => setActive(keyOf(item))}
					/>
				))}
			</nav>

			<div className="min-w-0 flex-1 overflow-auto px-5 py-4">
				{current && source ? (
					<SectionPage
						section={current.section}
						source={source}
						draft={drafts[source.id] ?? {}}
						secretDraft={secrets[source.id] ?? {}}
						onDraft={(id, value) => {
							setDrafts(currentDrafts => ({
								...currentDrafts,
								[source.id]: { ...currentDrafts[source.id], [id]: value },
							}));
						}}
						onSecret={(id, value) => {
							setSecrets(currentSecrets => ({
								...currentSecrets,
								[source.id]: { ...currentSecrets[source.id], [id]: value },
							}));
						}}
						onToggle={(id, value) => {
							setDrafts(currentDrafts => ({
								...currentDrafts,
								[source.id]: { ...currentDrafts[source.id], [id]: value },
							}));
							post({
								type: 'saveSettings',
								sourceId: source.id,
								values: { ...source.values, ...(drafts[source.id] ?? {}), [id]: value },
							});
						}}
						onAction={actionId => {
							if (actionId === 'save') {
								save();
								return;
							}
							if (actionId.startsWith('clearSecret:')) {
								save([actionId.slice('clearSecret:'.length)]);
								return;
							}
							post({
								type: 'runSettingsAction',
								sourceId: source.id,
								actionId,
								values: { ...source.values, ...(drafts[source.id] ?? {}) },
								secrets: secrets[source.id],
							});
						}}
					/>
				) : (
					<p className="text-xs text-muted">No settings contributors are loaded.</p>
				)}
			</div>
		</div>
	);
}

function SectionPage(props: {
	section: SettingsSection;
	source: SettingsSourceState;
	draft: Record<string, string | number | boolean>;
	secretDraft: Record<string, string>;
	onDraft: (id: string, value: string | number | boolean) => void;
	onSecret: (id: string, value: string) => void;
	onToggle: (id: string, value: boolean) => void;
	onAction: (id: string) => void;
}): JSX.Element {
	const chips = props.section.fields.filter(field => field.kind === 'status');
	const actions = props.section.fields.filter(field => field.kind === 'action');
	const inputs = props.section.fields.filter(field => field.kind !== 'status' && field.kind !== 'action');
	const onSelect = (id: string, value: string) => {
		props.onDraft(id, value);
		post({
			type: 'saveSettings',
			sourceId: props.source.id,
			values: { ...props.source.values, ...props.draft, [id]: value },
		});
	};
	return (
		<div className="flex flex-col gap-6">
			<div>
				<h2 className="text-base font-semibold">{props.section.title}</h2>
				{props.section.description ? (
					<p className="mt-1 text-xs text-muted">{props.section.description}</p>
				) : null}
			</div>
			{chips.length ? (
				<div className="flex flex-wrap gap-1.5">
					{chips.map(field => {
						const text = props.source.status[field.id];
						if (!text) {
							return null;
						}
						const warn = field.id === 'pythonMismatch' || /mismatch|not installed/i.test(text);
						return (
							<Chip key={field.id} size="sm" variant="soft" className={warn ? 'text-red-400' : undefined}>
								{text}
							</Chip>
						);
					})}
				</div>
			) : null}
			{inputs.map(field => (
				<FieldControl
					key={field.id}
					field={field}
					value={props.draft[field.id] ?? props.source.values[field.id]}
					secretValue={props.secretDraft[field.id] ?? ''}
					secretSet={Boolean(props.source.secretSet[field.id])}
					interpreters={props.source.interpreters ?? []}
					onDraft={props.onDraft}
					onSecret={props.onSecret}
					onToggle={props.onToggle}
					onSelect={onSelect}
				/>
			))}
			{actions.length ? (
				<div className="flex flex-wrap gap-1.5">
					{actions.map(field => (
						<div key={field.id} className="flex min-w-[calc(50%-0.375rem)] flex-1 flex-col items-stretch gap-1">
							<Button
								size="sm"
								variant={field.variant === 'primary' ? undefined : field.variant}
								isDisabled={field.id.startsWith('clearSecret:') && !secretEnabled(field, props.source)}
								onPress={() => props.onAction(field.id)}
							>
								{field.label ?? field.id}
							</Button>
							{field.description ? (
								<p className="text-[11px] leading-snug text-muted">{field.description}</p>
							) : null}
						</div>
					))}
				</div>
			) : null}
		</div>
	);
}

function FieldControl(props: {
	field: SettingsField;
	value: string | number | boolean | undefined;
	secretValue: string;
	secretSet: boolean;
	onDraft: (id: string, value: string | number | boolean) => void;
	onSecret: (id: string, value: string) => void;
	onToggle: (id: string, value: boolean) => void;
	onSelect: (id: string, value: string) => void;
	interpreters: InterpreterInfo[];
}): JSX.Element | null {
	const field = props.field;
	if (field.kind === 'toggle') {
		return (
			<div className="flex items-start justify-between gap-4">
				<div>
					<p className="text-sm font-semibold">{field.label}</p>
					{field.description ? <p className="mt-1 text-xs text-muted">{field.description}</p> : null}
				</div>
				<Switch isSelected={Boolean(props.value)} onChange={value => props.onToggle(field.id, value)} />
			</div>
		);
	}
	if (field.kind === 'secret') {
		return (
			<Labeled field={field}>
				<TextField name={field.id} type="password" value={props.secretValue} onChange={value => props.onSecret(field.id, value)}>
					<Input autoComplete="new-password" placeholder={props.secretSet ? '••••••••  (stored)' : field.placeholder} />
				</TextField>
			</Labeled>
		);
	}
	if (field.kind === 'number') {
		return (
			<Labeled field={field}>
				<TextField name={field.id} type="number" value={String(props.value ?? '')} onChange={value => props.onDraft(field.id, Number(value) || 0)}>
					<Input />
				</TextField>
			</Labeled>
		);
	}
	if (field.kind === 'text') {
		return (
			<Labeled field={field}>
				<TextField name={field.id} value={String(props.value ?? '')} onChange={value => props.onDraft(field.id, value)}>
					<Input placeholder={field.placeholder} />
				</TextField>
			</Labeled>
		);
	}
	if (field.kind === 'select') {
		const options = field.options ?? [];
		if (field.id === 'appIcon' || options.some(option => option.preview)) {
			return (
				<Labeled field={field}>
					<div className="flex flex-wrap gap-3">
						{options.map(option => {
							const selected = String(props.value ?? '') === option.value;
							return (
								<button
									key={option.value}
									type="button"
									className={`flex w-[104px] flex-col items-center gap-2 rounded-md border p-2.5 text-center ${
										selected ? 'border-accent bg-field-background' : 'border-separator bg-transparent'
									}`}
									onClick={() => props.onSelect(field.id, option.value)}
								>
									<span className="flex h-16 w-16 items-center justify-center overflow-visible">
										{option.preview ? (
											<img
												src={option.preview}
												alt={option.label}
												className="app-icon-preview h-16 w-16"
											/>
										) : (
											<span
												className="app-icon-preview-fallback flex h-16 w-16 items-center justify-center text-[10px] text-muted"
												data-variant={option.value}
											>
												{option.label}
											</span>
										)}
									</span>
									<span className="text-[11px] leading-tight text-foreground">{option.label}</span>
								</button>
							);
						})}
					</div>
				</Labeled>
			);
		}
		return (
			<Labeled field={field}>
				<select
					className="w-full rounded-md border border-separator bg-field-background px-2 py-1.5 text-sm text-foreground"
					name={field.id}
					value={String(props.value ?? '')}
					onChange={event => props.onSelect(field.id, event.target.value)}
				>
					{options.map(option => (
						<option key={option.value} value={option.value}>
							{option.label}
						</option>
					))}
				</select>
			</Labeled>
		);
	}
	if (field.kind === 'interpreter') {
		return (
			<InterpreterField
				field={field}
				value={String(props.value ?? '')}
				interpreters={props.interpreters}
				onSelect={props.onSelect}
				onDraft={props.onDraft}
			/>
		);
	}
	return null;
}

function InterpreterField(props: {
	field: SettingsField;
	value: string;
	interpreters: InterpreterInfo[];
	onSelect: (id: string, value: string) => void;
	onDraft: (id: string, value: string | number | boolean) => void;
}): JSX.Element {
	const [path, setPath] = useState(props.value);
	useEffect(() => {
		setPath(props.value);
	}, [props.value]);
	const selected = props.interpreters.find(item => item.path === props.value);
	const mismatch = selected ? !selected.compatible : Boolean(props.value) && !props.interpreters.some(item => item.path === props.value);
	const commit = () => {
		const next = path.trim();
		if (!next || next === props.value) {
			return;
		}
		props.onDraft(props.field.id, next);
		props.onSelect(props.field.id, next);
	};
	return (
		<Labeled field={props.field}>
			<div className="flex flex-col gap-2">
				<TextField
					name={props.field.id}
					value={path}
					isInvalid={mismatch}
					onChange={value => {
						setPath(value);
						props.onDraft(props.field.id, value);
					}}
				>
					<Input
						placeholder={props.field.placeholder}
						onBlur={commit}
						onKeyDown={event => {
							if (event.key === 'Enter') {
								event.preventDefault();
								commit();
							}
						}}
					/>
					{mismatch ? (
						<FieldError>
							{selected
								? `Python ${selected.version} cannot install NetSquid. Choose 3.8–3.11.`
								: 'This path is not a known compatible interpreter. Check the version before installing.'}
						</FieldError>
					) : null}
				</TextField>
				{!mismatch && selected?.netsquid ? (
					<p className="text-xs text-muted">Python {selected.version} · NetSquid {selected.netsquid}</p>
				) : !mismatch && selected ? (
					<p className="text-xs text-muted">Python {selected.version} matches NetSquid. Engine not installed in this interpreter yet.</p>
				) : null}
				<ul className="space-y-1.5">
					{props.interpreters.map(item => (
						<li key={item.path}>
							<button
								type="button"
								className={`w-full rounded-md border px-2 py-1.5 text-left text-xs ${item.path === props.value ? 'border-accent bg-accent/10' : 'border-separator'} ${item.compatible ? '' : 'opacity-70'}`}
								onClick={() => props.onSelect(props.field.id, item.path)}
							>
								<div className="flex flex-wrap items-center gap-1.5">
									<span className={item.compatible ? 'font-semibold' : 'text-red-400'}>
										{item.compatible ? 'Usable' : 'Mismatch'}
									</span>
									<span>Python {item.version}</span>
									{item.netsquid ? <span>NetSquid {item.netsquid}</span> : null}
								</div>
								<p className="mt-0.5 break-all font-mono text-[11px] text-muted">{item.path}</p>
							</button>
						</li>
					))}
				</ul>
			</div>
		</Labeled>
	);
}

function Labeled(props: { field: SettingsField; children: JSX.Element }): JSX.Element {
	return (
		<div className="flex flex-col gap-2">
			<div>
				<p className="text-sm font-semibold">{props.field.label}</p>
				{props.field.description ? <p className="mt-1 text-xs text-muted">{props.field.description}</p> : null}
			</div>
			{props.children}
		</div>
	);
}

function NavItem(props: { label: string; icon?: SettingsSection['icon']; active: boolean; onSelect: () => void }): JSX.Element {
	return (
		<button
			type="button"
			className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs ${props.active ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-default'}`}
			onClick={props.onSelect}
		>
			<span className="size-3.5 [&_svg]:size-3.5">{iconFor(props.icon)}</span>
			{props.label}
		</button>
	);
}

function flatten(sources: SettingsSourceState[]): SectionRef[] {
	return sources
		.flatMap(source => source.sections.map(section => ({ sourceId: source.id, section })))
		.sort((a, b) => (a.section.order ?? 100) - (b.section.order ?? 100));
}

function keyOf(item: SectionRef): string {
	return `${item.sourceId}/${item.section.id}`;
}

function secretEnabled(field: SettingsField, source: SettingsSourceState): boolean {
	const id = field.id.startsWith('clearSecret:') ? field.id.slice('clearSecret:'.length) : field.id;
	return Boolean(source.secretSet[id]);
}

function iconFor(icon: SettingsSection['icon']): JSX.Element {
	if (icon === 'flask') {
		return <Flask />;
	}
	if (icon === 'gear') {
		return <Gear />;
	}
	return <CircleInfo />;
}
