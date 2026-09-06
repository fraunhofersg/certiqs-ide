import { FolderOpen, ArrowRotateRight, Plus } from '@gravity-ui/icons';
import { Accordion, Button, Chip, Input, TextField } from '@heroui/react';
import { EmptyState } from '@heroui-pro/react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import type { KnowledgeSnapshot, SessionKind, SessionSummary } from '../../src/knowledgeTypes';
import type { HqState } from '../../src/protocol';
import type { RuntimeAction, RuntimeSnapshot } from '../../src/runtimeContract';
import { onHostMessage, post } from './vscodeApi';

const INITIAL: HqState = {
	fixtureLoaded: false,
	skills: [],
	mcpConfigured: false,
	labels: ['synthetic', 'not a measurement', 'not a security or conformity statement'],
	notice: 'Demo counters stay at zero. This panel does not call a model provider or measure cost.',
};

export function HqHome(): JSX.Element {
	const [state, setState] = useState<HqState>(INITIAL);
	const [runtimes, setRuntimes] = useState<RuntimeSnapshot[]>([]);
	const [slug, setSlug] = useState('');

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'state') {
				setState(message.payload);
			}
			if (message.type === 'knowledge') {
				setState(current => ({ ...current, knowledge: message.payload }));
			}
			if (message.type === 'runtimes') {
				setRuntimes(message.payload);
			}
		});
		post({ type: 'ready' });
		return dispose;
	}, []);

	const knowledge = state.knowledge;
	const sessions = knowledge?.sessions ?? [];
	const groups = useMemo(() => ({
		brainstorm: sessions.filter(item => item.kind === 'brainstorm' && !item.archived),
		architect: sessions.filter(item => item.kind === 'architect' && !item.archived),
		chat: sessions.filter(item => item.kind === 'chat' && !item.archived),
		archived: sessions.filter(item => item.archived),
	}), [sessions]);

	const onCreateSkill = (event: FormEvent) => {
		event.preventDefault();
		if (!slug.trim()) {
			return;
		}
		post({ type: 'createSkill', slug });
		setSlug('');
	};

	return (
		<div className="flex h-full min-h-0 flex-col">
			<div className="flex border-b border-separator">
				<button type="button" className="flex-1 border-b-2 border-accent px-2 py-2 text-xs font-semibold text-accent">HQ</button>
				<button type="button" className="flex-1 px-2 py-2 text-xs text-muted hover:text-foreground" onClick={() => post({ type: 'openSettings' })}>
					Settings
				</button>
			</div>

			<div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3">
				<div className="hq-explorer-actions">
					<Button size="sm" onPress={() => post({ type: 'openContextLens' })}>Open Context Lens</Button>
					<Button size="sm" variant="outline" onPress={() => post({ type: 'newSession', kind: 'brainstorm' })}>New Brainstorming</Button>
					<Button size="sm" variant="outline" onPress={() => post({ type: 'newSession', kind: 'architect' })}>New Architect</Button>
					<Button size="sm" variant="outline" onPress={() => post({ type: 'newSession', kind: 'chat' })}>New Chat Session</Button>
				</div>

				<Accordion allowsMultipleExpanded className="w-full" defaultExpandedKeys={['explorer', 'skills']} hideSeparator>
					<Accordion.Item id="explorer">
						<Accordion.Heading>
							<Accordion.Trigger>
								Explorer
								<Accordion.Indicator />
							</Accordion.Trigger>
						</Accordion.Heading>
						<Accordion.Panel>
							<Accordion.Body>
								<SessionGroup title="Brainstorming" kind="brainstorm" items={groups.brainstorm} />
								<SessionGroup title="Architect" kind="architect" items={groups.architect} />
								<SessionGroup title="Sessions" kind="chat" items={groups.chat} />
								<SessionGroup title="Archived Sessions" items={groups.archived} />
							</Accordion.Body>
						</Accordion.Panel>
					</Accordion.Item>

					<Accordion.Item id="skills">
						<Accordion.Heading>
							<Accordion.Trigger>
								Skills
								<Accordion.Indicator />
							</Accordion.Trigger>
						</Accordion.Heading>
						<Accordion.Panel>
							<Accordion.Body>
								<form className="mb-3 flex items-end gap-2" onSubmit={onCreateSkill}>
									<TextField aria-label="Skill slug" className="min-w-0 flex-1" name="skill-slug" value={slug} onChange={setSlug}>
										<Input placeholder="skill-slug (e.g. my-skill)" />
									</TextField>
									<Button size="sm" type="submit">Create</Button>
									<Button isIconOnly aria-label="Refresh" size="sm" type="button" variant="outline" onPress={() => post({ type: 'refresh' })}>
										<ArrowRotateRight />
									</Button>
								</form>
								{state.skills.length === 0 ? (
									<EmptyState>
										<EmptyState.Header>
											<EmptyState.Media variant="icon"><FolderOpen /></EmptyState.Media>
											<EmptyState.Title>No skills found</EmptyState.Title>
											<EmptyState.Description>Create a SKILL.md file in .certiqs/skills/ to get started.</EmptyState.Description>
										</EmptyState.Header>
									</EmptyState>
								) : (
									<ul className="space-y-1 text-sm">
										{state.skills.map(skill => <li key={skill.slug}>{skill.slug}</li>)}
									</ul>
								)}
							</Accordion.Body>
						</Accordion.Panel>
					</Accordion.Item>

					<Accordion.Item id="monitoring">
						<Accordion.Heading>
							<Accordion.Trigger>
								Monitoring
								<Accordion.Indicator />
							</Accordion.Trigger>
						</Accordion.Heading>
						<Accordion.Panel>
							<Accordion.Body>
								<TokenStrip knowledge={knowledge} />
								<p className="mb-2 text-xs text-muted">{state.notice}</p>
								<div className="mb-3 flex flex-wrap gap-1.5">
									{state.labels.map(label => <Chip key={label} size="sm" variant="soft">{label}</Chip>)}
								</div>
								<div className="mb-2 flex justify-end">
									<Button size="sm" variant="outline" onPress={() => post({ type: 'readyRuntimes' })}>Refresh</Button>
								</div>
								{runtimes.length === 0 ? (
									<p className="text-xs text-muted">No API services contributed.</p>
								) : runtimes.map(runtime => <ServiceCard key={runtime.id} runtime={runtime} />)}
							</Accordion.Body>
						</Accordion.Panel>
					</Accordion.Item>

					<Accordion.Item id="models">
						<Accordion.Heading>
							<Accordion.Trigger>
								Models
								<Accordion.Indicator />
							</Accordion.Trigger>
						</Accordion.Heading>
						<Accordion.Panel>
							<Accordion.Body>
								<div className="mb-2 flex flex-wrap gap-2">
									<Chip size="sm" variant="soft">Local</Chip>
									<Chip size="sm" variant="secondary">None</Chip>
								</div>
								<p className="text-xs text-muted">No model gallery is shipped. Sessions persist locally and do not send traffic.</p>
							</Accordion.Body>
						</Accordion.Panel>
					</Accordion.Item>

					<Accordion.Item id="mcp">
						<Accordion.Heading>
							<Accordion.Trigger>
								MCP Servers
								<Accordion.Indicator />
							</Accordion.Trigger>
						</Accordion.Heading>
						<Accordion.Panel>
							<Accordion.Body>
								<Button className="mb-3" fullWidth size="sm" onPress={() => post({ type: 'editMcpJson' })}>Edit mcp.json</Button>
								{state.mcpConfigured ? (
									<p className="text-xs text-muted">Workspace MCP config is present.</p>
								) : (
									<EmptyState>
										<EmptyState.Header>
											<EmptyState.Title>No MCP servers configured</EmptyState.Title>
											<EmptyState.Description>Click Edit mcp.json to add servers.</EmptyState.Description>
										</EmptyState.Header>
									</EmptyState>
								)}
							</Accordion.Body>
						</Accordion.Panel>
					</Accordion.Item>
				</Accordion>
			</div>
		</div>
	);
}

function SessionGroup(props: { title: string; kind?: SessionKind; items: SessionSummary[] }): JSX.Element {
	return (
		<div className="mb-2">
			<div className="flex items-center justify-between py-1">
				<p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{props.title}</p>
				{props.kind ? (
					<button type="button" className="text-muted hover:text-accent" aria-label={`New ${props.title}`} onClick={() => post({ type: 'newSession', kind: props.kind! })}>
						<Plus className="size-3.5" />
					</button>
				) : null}
			</div>
			{props.items.length === 0 ? (
				<p className="px-1 py-0.5 text-[11px] text-muted/70">None yet</p>
			) : (
				<ul className="space-y-0.5">
					{props.items.map(item => (
						<li key={item.id}>
							<button
								type="button"
								className="w-full truncate rounded px-1 py-1 text-left text-xs hover:bg-surface"
								onClick={() => post({ type: 'openSession', id: item.id })}
							>
								{item.title}
							</button>
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

function TokenStrip(props: { knowledge?: KnowledgeSnapshot }): JSX.Element {
	const tokens = props.knowledge?.tokens;
	const used = tokens ? tokens.loom + tokens.wiki + tokens.knot + tokens.system : 0;
	return (
		<div className="mb-3 grid grid-cols-4 gap-2">
			<Stat value={String(props.knowledge?.sessions.length ?? 0)} label="Sessions" />
			<Stat value="0" label="LLM Calls" />
			<Stat value={used.toLocaleString()} label="Tokens" />
			<Stat value="$0.00" label="Cost" />
		</div>
	);
}

function ServiceCard(props: { runtime: RuntimeSnapshot }): JSX.Element {
	const runtime = props.runtime;
	const docker = runtime.mode === 'docker';
	const action = (type: RuntimeAction) => post({ type: 'runtimeAction', sourceId: runtime.id, action: type });
	return (
		<div className="mb-2 rounded-md border border-separator p-3">
			<div className="mb-2 flex flex-wrap items-center gap-1.5">
				<p className="text-sm font-semibold">{runtime.title}</p>
				<Chip size="sm" variant="soft">{runtime.mode}</Chip>
				<Chip size="sm" variant={runtime.state === 'ready' ? 'secondary' : 'soft'}>{runtime.state}</Chip>
			</div>
			<ul className="mb-3 space-y-1 text-xs text-muted">
				<li>Endpoint — {runtime.endpoint ?? 'none'}</li>
				{docker ? (
					<>
						<li>Docker — {runtime.docker?.available ? 'available' : 'not installed'}</li>
						<li>Image — {runtime.docker?.image ?? 'certiqs-sim:local'}</li>
					</>
				) : null}
			</ul>
			<div className="flex flex-wrap gap-1.5">
				<Button size="sm" onPress={() => action('start')}>Start</Button>
				<Button size="sm" variant="outline" onPress={() => action('stop')}>Stop</Button>
				<Button size="sm" variant="outline" onPress={() => action('logs')}>Logs</Button>
			</div>
		</div>
	);
}

function Stat(props: { value: string; label: string }): JSX.Element {
	return (
		<div className="flex flex-col gap-0.5">
			<strong className="text-base leading-none tabular-nums">{props.value}</strong>
			<span className="text-muted text-[10px]">{props.label}</span>
		</div>
	);
}
