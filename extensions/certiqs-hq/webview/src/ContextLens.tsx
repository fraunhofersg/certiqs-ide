import { Button, Card, Chip, Input, TextField } from '@heroui/react';
import { useEffect, useMemo, useState } from 'react';
import type { KnowledgeSnapshot, LoomEntry, WikiStrategy } from '../../src/knowledgeTypes';
import { rpc } from './hostRpc';
import { onHostMessage, post } from './vscodeApi';

type LensMode = 'both' | 'knot' | 'knowledge' | 'preview';

const STRATEGIES: { id: WikiStrategy; label: string }[] = [
	{ id: 'all', label: 'All Source' },
	{ id: 'auto', label: 'Auto-Detected Only' },
	{ id: 'manual', label: 'Manual Files Only' },
	{ id: 'index', label: 'Index Only' },
];

export function ContextLens(): JSX.Element {
	const [knowledge, setKnowledge] = useState<KnowledgeSnapshot | undefined>();
	const [mode, setMode] = useState<LensMode>('knowledge');
	const [query, setQuery] = useState('');
	const [wikiQuery, setWikiQuery] = useState('');
	const [prompt, setPrompt] = useState('');
	const [notice, setNotice] = useState<string>();

	useEffect(() => {
		const dispose = onHostMessage(message => {
			if (message.type === 'knowledge' || (message.type === 'state' && message.payload.knowledge)) {
				setKnowledge(message.type === 'knowledge' ? message.payload : message.payload.knowledge);
			}
		});
		post({ type: 'ready' });
		void rpc<KnowledgeSnapshot>('getKnowledge').then(setKnowledge).catch(error => setNotice((error as Error).message));
		return dispose;
	}, []);

	const tokens = knowledge?.tokens;
	const used = tokens ? tokens.loom + tokens.wiki + tokens.knot + tokens.system : 0;
	const input = tokens?.input ?? 840000;
	const pct = Math.min(100, (used / input) * 100);

	const entries = useMemo(() => {
		const q = query.trim().toLowerCase();
		return (knowledge?.loom.entries ?? []).filter(entry => {
			if (!q) {
				return true;
			}
			return `${entry.category} ${entry.title} ${entry.body}`.toLowerCase().includes(q);
		});
	}, [knowledge, query]);

	const wikiPaths = useMemo(() => {
		if (!knowledge) {
			return [];
		}
		const { wiki } = knowledge;
		const all = wiki.strategy === 'manual' ? wiki.manual
			: wiki.strategy === 'auto' || wiki.strategy === 'index' ? wiki.autoDetected
				: [...new Set([...wiki.autoDetected, ...wiki.manual])];
		const q = wikiQuery.trim().toLowerCase();
		return all.filter(path => !q || path.toLowerCase().includes(q));
	}, [knowledge, wikiQuery]);

	const runReviewer = async (action: string) => {
		try {
			const result = await rpc<{ message: string }>('reviewerAction', { action });
			setNotice(result.message);
		} catch (error) {
			setNotice((error as Error).message);
		}
	};

	const addWiki = async () => {
		const path = wikiQuery.trim();
		if (!path) {
			return;
		}
		await rpc('addWikiFile', { path });
		setWikiQuery('');
	};

	return (
		<div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-5">
			<header className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<p className="text-xs font-semibold tracking-wide text-accent">Context Lens</p>
					<h1 className="text-xl font-semibold">Inspect what certiqs would send</h1>
					<p className="text-xs text-muted">{knowledge?.notice}</p>
				</div>
				<div className="min-w-[280px] flex-1">
					<div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
						<span>TOKEN BUDGET input {input.toLocaleString()} reserved output {(tokens?.reservedOutput ?? 210000).toLocaleString()}</span>
						<span>{used.toLocaleString()} / {input.toLocaleString()} ({pct.toFixed(1)}%)</span>
					</div>
					<div className="mt-1 h-1.5 overflow-hidden rounded-full bg-separator">
						<div className="h-full bg-accent" style={{ width: `${Math.max(pct, 1)}%` }} />
					</div>
					<p className="mt-1 text-[11px] text-muted">
						loom {(tokens?.loom ?? 0).toLocaleString()} · wiki {(tokens?.wiki ?? 0).toLocaleString()} · knot {(tokens?.knot ?? 0).toLocaleString()} · system {(tokens?.system ?? 0).toLocaleString()}
					</p>
				</div>
			</header>

			<div className="flex flex-wrap gap-1.5">
				{([
					['both', 'Both'],
					['knot', 'Knot'],
					['knowledge', 'Knowledge'],
					['preview', 'LLM Preview'],
				] as const).map(([id, label]) => (
					<button
						key={id}
						type="button"
						onClick={() => setMode(id)}
						className={`rounded-md px-3 py-1.5 text-xs ${mode === id ? 'bg-accent/15 font-semibold text-accent' : 'text-muted hover:text-foreground'}`}
					>
						{label}
					</button>
				))}
			</div>

			{notice ? <Card className="p-3 text-sm">{notice}</Card> : null}

			{mode === 'preview' ? (
				<Card className="p-4 font-mono text-xs whitespace-pre-wrap text-muted">
					{previewText(knowledge)}
				</Card>
			) : (
				<div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-2">
					{(mode === 'both' || mode === 'knowledge') ? (
						<section className="flex min-h-0 flex-col gap-3">
							<div className="flex items-center justify-between">
								<h2 className="text-sm font-semibold">Global Knowledge</h2>
								<Chip size="sm" variant="soft">{entries.length} entries</Chip>
							</div>
							<TextField name="knowledge-search" value={query} onChange={setQuery}>
								<Input placeholder="Search global knowledge…" />
							</TextField>
							{entries.length === 0 ? (
								<Card className="p-6 text-sm text-muted">No global knowledge entries yet.</Card>
							) : (
								<div className="flex flex-col gap-2">
									{entries.map(entry => <LoomCard key={entry.id} entry={entry} />)}
								</div>
							)}
						</section>
					) : null}

					{(mode === 'both' || mode === 'knot' || mode === 'knowledge') ? (
						<section className="flex min-h-0 flex-col gap-3">
							{mode !== 'knot' ? (
								<>
									<div className="flex items-center justify-between gap-2">
										<h2 className="text-sm font-semibold">Wiki</h2>
										<Button size="sm" variant="outline" onPress={() => void addWiki()}>Add File</Button>
									</div>
									<TextField name="wiki-search" value={wikiQuery} onChange={setWikiQuery}>
										<Input placeholder="Search wiki sources… or paste a relative path" />
									</TextField>
									<div className="flex flex-wrap gap-1">
										{STRATEGIES.map(item => (
											<button
												key={item.id}
												type="button"
												onClick={() => void rpc('setWikiStrategy', { strategy: item.id })}
												className={`rounded-md px-2.5 py-1 text-[11px] ${knowledge?.wiki.strategy === item.id ? 'bg-accent/15 text-accent' : 'text-muted hover:text-foreground'}`}
											>
												{item.label}
											</button>
										))}
									</div>
									{wikiPaths.length === 0 ? (
										<p className="text-sm text-muted">No wiki sources yet. Add a repository file or rely on automatic discovery.</p>
									) : (
										<ul className="space-y-1 text-xs">
											{wikiPaths.map(path => (
												<li key={path} className="flex items-center justify-between gap-2 rounded border border-separator px-2 py-1.5">
													<span className="truncate font-mono">{path}</span>
													{knowledge?.wiki.manual.includes(path) ? (
														<button type="button" className="text-muted hover:text-foreground" onClick={() => void rpc('removeWikiFile', { path })}>Remove</button>
													) : null}
												</li>
											))}
										</ul>
									)}
								</>
							) : null}

							<div>
								<h2 className="mb-2 text-sm font-semibold">Session knot</h2>
								{(knowledge?.activeSession?.knot.length ?? 0) === 0 ? (
									<p className="text-sm text-muted">No active session knot. Open a chat, brainstorm, or architect tab first.</p>
								) : (
									<ul className="space-y-2">
										{knowledge?.activeSession?.knot.map(item => (
											<li key={item.id} className="rounded-md border border-separator p-3">
												<p className="text-sm font-semibold">{item.title}</p>
												<p className="mt-1 text-xs text-muted whitespace-pre-wrap">{item.body}</p>
											</li>
										))}
									</ul>
								)}
							</div>
						</section>
					) : null}
				</div>
			)}

			<section className="rounded-md border border-separator p-4">
				<p className="text-sm font-semibold">Context Reviewer</p>
				<p className="mb-3 text-xs text-muted">AI-powered context management. Local actions only — no model is called.</p>
				<div className="mb-3 flex flex-wrap gap-1.5">
					<Button size="sm" onPress={() => void runReviewer('initialize')}>Initialize global knowledge</Button>
					<Button size="sm" variant="outline" onPress={() => void runReviewer('summarizeToolResults')}>Summarize Old Tool Results</Button>
					<Button size="sm" variant="outline" onPress={() => void runReviewer('removeDuplicates')}>Remove Duplicates</Button>
					<Button size="sm" variant="outline" onPress={() => void runReviewer('refreshStaleLoom')}>Refresh Stale Loom</Button>
					<Button size="sm" variant="outline" onPress={() => void runReviewer('optimizeTokens')}>Optimize Token Usage</Button>
				</div>
				<div className="flex gap-2">
					<TextField name="reviewer-prompt" className="flex-1" value={prompt} onChange={setPrompt}>
						<Input
							placeholder="Ask the reviewer to modify context…"
							onKeyDown={event => {
								if (event.key === 'Enter' && prompt.trim()) {
									void runReviewer(prompt.toLowerCase().includes('init') ? 'initialize' : 'refreshStaleLoom');
									setPrompt('');
								}
							}}
						/>
					</TextField>
					<Button size="sm" onPress={() => {
						if (prompt.trim()) {
							void runReviewer(prompt.toLowerCase().includes('init') ? 'initialize' : 'refreshStaleLoom');
							setPrompt('');
						}
					}}>
						Send
					</Button>
				</div>
			</section>
		</div>
	);
}

function LoomCard(props: { entry: LoomEntry }): JSX.Element {
	return (
		<Card className={`p-3 ${props.entry.hidden ? 'opacity-50' : ''}`}>
			<div className="flex items-start justify-between gap-2">
				<div>
					<Chip size="sm" variant="soft">{props.entry.category}</Chip>
					<p className="mt-1 text-sm font-semibold">{props.entry.title}</p>
				</div>
				<div className="flex gap-1">
					<button type="button" className="text-[11px] text-muted hover:text-foreground" onClick={() => void rpc('toggleLoomHidden', { id: props.entry.id })}>
						{props.entry.hidden ? 'Show' : 'Hide'}
					</button>
					<button type="button" className="text-[11px] text-muted hover:text-foreground" onClick={() => void rpc('removeLoomEntry', { id: props.entry.id })}>
						Remove
					</button>
				</div>
			</div>
			<p className="mt-2 text-xs text-muted whitespace-pre-wrap">{props.entry.body.slice(0, 480)}{props.entry.body.length > 480 ? '…' : ''}</p>
			{props.entry.source ? <p className="mt-1 font-mono text-[10px] text-muted">{props.entry.source}</p> : null}
		</Card>
	);
}

function previewText(knowledge?: KnowledgeSnapshot): string {
	if (!knowledge) {
		return 'No context assembled.';
	}
	const loom = knowledge.loom.entries.filter(entry => !entry.hidden).map(entry => `[loom/${entry.category}] ${entry.title}\n${entry.body}`).join('\n\n');
	const knot = (knowledge.activeSession?.knot ?? []).map(item => `[knot] ${item.title}\n${item.body}`).join('\n\n');
	return [loom, knot].filter(Boolean).join('\n\n---\n\n') || 'Context is empty.';
}
