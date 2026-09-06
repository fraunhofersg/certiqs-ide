/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import {
	ArchitectStep,
	BrainstormBranch,
	ChatMessage,
	INPUT_TOKEN_BUDGET,
	KnowledgeSnapshot,
	KnotEntry,
	LoomEntry,
	LoomFile,
	RESERVED_OUTPUT_TOKENS,
	SYSTEM_TOKEN_BASE,
	SessionFile,
	SessionKind,
	SessionSummary,
	WikiFile,
	WikiStrategy,
	emptyLoom,
	emptyWiki,
	estimateTokens,
	newId,
} from './knowledgeTypes';

const NOTICE = 'Workspace-derived knowledge. Not a measurement and not a security or conformity statement.';

export class KnowledgeStore implements vscode.Disposable {
	private watcher: vscode.FileSystemWatcher | undefined;
	private readonly listeners = new Set<() => void>();
	private activeSessionId: string | undefined;

	onDidChange(listener: () => void): vscode.Disposable {
		this.listeners.add(listener);
		return { dispose: () => this.listeners.delete(listener) };
	}

	watch(): vscode.Disposable {
		const folder = workspaceFolder();
		if (!folder) {
			return { dispose() { } };
		}
		this.watcher?.dispose();
		this.watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, '.certiqs/**'));
		const fire = () => this.notify();
		this.watcher.onDidCreate(fire);
		this.watcher.onDidChange(fire);
		this.watcher.onDidDelete(fire);
		return this.watcher;
	}

	dispose(): void {
		this.watcher?.dispose();
		this.listeners.clear();
	}

	setActiveSession(id: string | undefined): void {
		this.activeSessionId = id;
		this.notify();
	}

	getActiveSessionId(): string | undefined {
		return this.activeSessionId;
	}

	async snapshot(): Promise<KnowledgeSnapshot> {
		const loom = await this.readLoom();
		const wiki = await this.readWiki();
		const sessions = await this.listSessions();
		const active = this.activeSessionId ? await this.readSession(this.activeSessionId) : undefined;
		return {
			loom,
			wiki,
			sessions,
			activeSession: active,
			tokens: this.tokenBudget(loom, wiki, active),
			workspaceName: workspaceFolder()?.name ?? 'workspace',
			notice: NOTICE,
		};
	}

	async readLoom(): Promise<LoomFile> {
		const uri = certiqsFile('brain.loom');
		const project = workspaceFolder()?.name ?? 'workspace';
		if (!uri || !(await pathExists(uri))) {
			return emptyLoom(project);
		}
		const raw = await readJson<Partial<LoomFile>>(uri);
		const entries = Array.isArray(raw.entries) ? raw.entries : [];
		return {
			version: typeof raw.version === 'number' ? raw.version : 3,
			projectName: raw.projectName ?? project,
			createdAt: raw.createdAt ?? new Date().toISOString(),
			updatedAt: raw.updatedAt ?? new Date().toISOString(),
			lastHardenedAt: raw.lastHardenedAt ?? null,
			messages: Array.isArray(raw.messages) ? raw.messages : [],
			entries,
		};
	}

	async writeLoom(loom: LoomFile): Promise<void> {
		const uri = await ensureCertiqsFile('brain.loom');
		loom.updatedAt = new Date().toISOString();
		await writeJson(uri, loom);
	}

	async readWiki(): Promise<WikiFile> {
		const uri = certiqsFile('wiki.json');
		const detected = await this.detectWikiSources();
		if (!uri || !(await pathExists(uri))) {
			return { ...emptyWiki(), autoDetected: detected };
		}
		const raw = await readJson<Partial<WikiFile>>(uri);
		return {
			strategy: raw.strategy ?? 'all',
			autoDetected: detected,
			manual: Array.isArray(raw.manual) ? raw.manual : [],
		};
	}

	async writeWiki(wiki: WikiFile): Promise<void> {
		const uri = await ensureCertiqsFile('wiki.json');
		await writeJson(uri, { strategy: wiki.strategy, manual: wiki.manual });
	}

	async setWikiStrategy(strategy: WikiStrategy): Promise<WikiFile> {
		const wiki = await this.readWiki();
		wiki.strategy = strategy;
		await this.writeWiki(wiki);
		return this.readWiki();
	}

	async addWikiFile(relPath: string): Promise<WikiFile> {
		const wiki = await this.readWiki();
		if (!wiki.manual.includes(relPath)) {
			wiki.manual.push(relPath);
			await this.writeWiki(wiki);
		}
		return this.readWiki();
	}

	async removeWikiFile(relPath: string): Promise<WikiFile> {
		const wiki = await this.readWiki();
		wiki.manual = wiki.manual.filter(item => item !== relPath);
		await this.writeWiki(wiki);
		return this.readWiki();
	}

	async toggleLoomHidden(id: string): Promise<LoomFile> {
		const loom = await this.readLoom();
		loom.entries = loom.entries.map(entry => entry.id === id ? { ...entry, hidden: !entry.hidden } : entry);
		await this.writeLoom(loom);
		return loom;
	}

	async removeLoomEntry(id: string): Promise<LoomFile> {
		const loom = await this.readLoom();
		loom.entries = loom.entries.filter(entry => entry.id !== id);
		await this.writeLoom(loom);
		return loom;
	}

	async initializeKnowledge(): Promise<LoomFile> {
		const loom = await this.readLoom();
		const generated = await this.scanWorkspace();
		const bySource = new Map(loom.entries.filter(entry => entry.source).map(entry => [entry.source!, entry]));
		for (const next of generated) {
			const existing = next.source ? bySource.get(next.source) : undefined;
			if (existing) {
				existing.body = next.body;
				existing.title = next.title;
				existing.category = next.category;
				existing.updatedAt = next.updatedAt;
			} else {
				loom.entries.push(next);
			}
		}
		if (generated.length === 0 && loom.entries.length === 0) {
			loom.entries.push(this.fallbackEntry());
		}
		await this.writeLoom(loom);
		return loom;
	}

	async reviewerAction(action: string): Promise<string> {
		const loom = await this.readLoom();
		if (action === 'removeDuplicates') {
			const seen = new Set<string>();
			loom.entries = loom.entries.filter(entry => {
				const key = `${entry.category}:${entry.title.toLowerCase()}`;
				if (seen.has(key)) {
					return false;
				}
				seen.add(key);
				return true;
			});
			await this.writeLoom(loom);
			return 'Removed duplicate loom titles.';
		}
		if (action === 'refreshStaleLoom') {
			await this.initializeKnowledge();
			return 'Refreshed workspace-derived loom entries.';
		}
		if (action === 'optimizeTokens') {
			const ranked = [...loom.entries].sort((a, b) => estimateTokens(b.body) - estimateTokens(a.body));
			for (const entry of ranked.slice(0, Math.max(0, ranked.length - 6))) {
				entry.hidden = true;
			}
			await this.writeLoom(loom);
			return 'Hid the longest loom entries to reduce the estimated budget.';
		}
		if (action === 'summarizeToolResults') {
			const session = this.activeSessionId ? await this.readSession(this.activeSessionId) : undefined;
			if (!session) {
				return 'No active session knot to summarize.';
			}
			if (session.knot.length === 0) {
				return 'Session knot is empty.';
			}
			const summary: KnotEntry = {
				id: newId('knot'),
				title: 'Summarized knot',
				body: session.knot.map(item => `${item.title}: ${item.body}`).join('\n').slice(0, 2000),
				updatedAt: new Date().toISOString(),
			};
			session.knot = [summary];
			await this.writeSession(session);
			return 'Collapsed session knot entries into one summary.';
		}
		if (action === 'initialize') {
			await this.initializeKnowledge();
			return 'Initialized global knowledge from the workspace.';
		}
		return 'Unknown reviewer action.';
	}

	async listSessions(): Promise<SessionSummary[]> {
		const root = certiqsFile('sessions');
		if (!root || !(await pathExists(root))) {
			return [];
		}
		const entries = await vscode.workspace.fs.readDirectory(root);
		const sessions: SessionSummary[] = [];
		for (const [name, type] of entries) {
			if (type !== vscode.FileType.File || !name.endsWith('.json')) {
				continue;
			}
			const file = await this.readSession(name.replace(/\.json$/, ''));
			if (file) {
				sessions.push({
					id: file.id,
					kind: file.kind,
					title: file.title,
					archived: file.archived,
					updatedAt: file.updatedAt,
				});
			}
		}
		return sessions.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
	}

	async readSession(id: string): Promise<SessionFile | undefined> {
		const uri = certiqsFile('sessions', `${id}.json`);
		if (!uri || !(await pathExists(uri))) {
			return undefined;
		}
		return readJson<SessionFile>(uri);
	}

	async writeSession(session: SessionFile): Promise<void> {
		session.updatedAt = new Date().toISOString();
		const uri = await ensureCertiqsFile('sessions', `${session.id}.json`);
		await writeJson(uri, session);
	}

	async createSession(kind: SessionKind, title?: string): Promise<SessionFile> {
		const labels: Record<SessionKind, string> = {
			chat: 'Chat Session',
			brainstorm: 'Brainstorming',
			architect: 'Architect',
		};
		const session: SessionFile = {
			id: newId(kind),
			kind,
			title: title?.trim() || `${labels[kind]} ${new Date().toLocaleString()}`,
			archived: false,
			knot: [],
			messages: [],
			branches: kind === 'brainstorm' ? [] : undefined,
			steps: kind === 'architect' ? [] : undefined,
			updatedAt: new Date().toISOString(),
		};
		await this.writeSession(session);
		this.activeSessionId = session.id;
		return session;
	}

	async archiveSession(id: string, archived = true): Promise<SessionFile | undefined> {
		const session = await this.readSession(id);
		if (!session) {
			return undefined;
		}
		session.archived = archived;
		await this.writeSession(session);
		return session;
	}

	async appendMessage(id: string, text: string, role: ChatMessage['role'] = 'user'): Promise<SessionFile | undefined> {
		const session = await this.readSession(id);
		if (!session) {
			return undefined;
		}
		const message: ChatMessage = {
			id: newId('msg'),
			role,
			text,
			createdAt: new Date().toISOString(),
		};
		session.messages.push(message);
		if (role === 'user') {
			session.knot.push({
				id: newId('knot'),
				title: text.slice(0, 48) || 'Note',
				body: text,
				updatedAt: message.createdAt,
			});
		}
		await this.writeSession(session);
		return session;
	}

	async updateSession(id: string, patch: Partial<SessionFile>): Promise<SessionFile | undefined> {
		const session = await this.readSession(id);
		if (!session) {
			return undefined;
		}
		const next = { ...session, ...patch, id: session.id, kind: session.kind };
		await this.writeSession(next);
		return next;
	}

	async approveSpec(id: string): Promise<SessionFile | undefined> {
		const session = await this.readSession(id);
		if (!session) {
			return undefined;
		}
		const selected = (session.branches ?? []).filter(branch => branch.selected);
		const spec = session.spec?.trim() || this.specFromBranches(session.intent, selected);
		const slug = slugify(session.title);
		const uri = await ensureCertiqsFile('spec', `${slug}.md`);
		const body = [
			`# ${session.title}`,
			'',
			NOTICE,
			'',
			session.intent ? `## Intent\n\n${session.intent}\n` : '',
			'## Spec',
			'',
			spec,
			'',
		].join('\n');
		await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(body));
		session.spec = spec;
		session.specPath = vscode.workspace.asRelativePath(uri);
		await this.writeSession(session);
		return session;
	}

	async sendToArchitect(id: string): Promise<SessionFile> {
		const source = await this.readSession(id);
		const spec = source?.spec ?? '';
		const steps = this.stepsFromSpec(spec || source?.intent || 'Plan QKD and security work');
		const session = await this.createSession('architect', source ? `Architect · ${source.title}` : undefined);
		session.specSource = source?.id;
		session.spec = spec;
		session.intent = source?.intent;
		session.steps = steps;
		await this.writeSession(session);
		return session;
	}

	private tokenBudget(loom: LoomFile, wiki: WikiFile, session?: SessionFile) {
		const visibleLoom = loom.entries.filter(entry => !entry.hidden);
		const loomTokens = visibleLoom.reduce((sum, entry) => sum + estimateTokens(`${entry.title}\n${entry.body}`), 0);
		const wikiPaths = this.wikiPaths(wiki);
		const wikiTokens = wiki.strategy === 'index'
			? estimateTokens(wikiPaths.join('\n'))
			: wikiPaths.reduce((sum, path) => sum + estimateTokens(path) + 80, 0);
		const knotTokens = (session?.knot ?? []).filter(item => !item.hidden)
			.reduce((sum, item) => sum + estimateTokens(`${item.title}\n${item.body}`), 0);
		return {
			input: INPUT_TOKEN_BUDGET,
			reservedOutput: RESERVED_OUTPUT_TOKENS,
			loom: loomTokens,
			wiki: wikiTokens,
			knot: knotTokens,
			system: SYSTEM_TOKEN_BASE,
		};
	}

	private wikiPaths(wiki: WikiFile): string[] {
		if (wiki.strategy === 'manual') {
			return wiki.manual;
		}
		if (wiki.strategy === 'auto' || wiki.strategy === 'index') {
			return wiki.autoDetected;
		}
		return [...new Set([...wiki.autoDetected, ...wiki.manual])];
	}

	private async detectWikiSources(): Promise<string[]> {
		const folder = workspaceFolder();
		if (!folder) {
			return [];
		}
		const found = await vscode.workspace.findFiles(
			new vscode.RelativePattern(folder, '{README*,00_manifest.yaml,docs/**/*.md,.certiqs/**/*.md}'),
			undefined,
			40,
		);
		return found.map(uri => vscode.workspace.asRelativePath(uri)).sort();
	}

	private async scanWorkspace(): Promise<LoomEntry[]> {
		const folder = workspaceFolder();
		if (!folder) {
			return [];
		}
		const files = await vscode.workspace.findFiles(
			new vscode.RelativePattern(folder, '{README*,00_manifest.yaml,nodes/**/*.{yaml,yml,md},network/**/*.{yaml,yml,md},shared/**/*.{yaml,yml,md},.certiqs/**/*.{md,yaml,yml}}'),
			'**/{node_modules,out,media,.git}/**',
			80,
		);
		const now = new Date().toISOString();
		const buckets = new Map<string, string[]>();
		for (const uri of files) {
			const rel = vscode.workspace.asRelativePath(uri);
			const category = categorize(rel);
			const snippet = await readSnippet(uri);
			if (!snippet) {
				continue;
			}
			const list = buckets.get(category) ?? [];
			list.push(`- ${rel}\n${snippet}`);
			buckets.set(category, list);
		}
		return [...buckets.entries()].map(([category, parts]) => ({
			id: newId('loom'),
			category,
			title: `${category} from workspace`,
			body: `${NOTICE}\n\n${parts.slice(0, 8).join('\n\n')}`.slice(0, 4000),
			source: `scan:${category}`,
			updatedAt: now,
		}));
	}

	private fallbackEntry(): LoomEntry {
		return {
			id: newId('loom'),
			category: 'Open questions',
			title: 'No QKD sources found',
			body: `${NOTICE}\n\nOpen a QKD workspace (manifest, nodes, network, shared) and run Initialize global knowledge again.`,
			source: 'scan:empty',
			updatedAt: new Date().toISOString(),
		};
	}

	private specFromBranches(intent: string | undefined, branches: BrainstormBranch[]): string {
		const lines = [
			intent ? `Intent: ${intent}` : 'Intent: (unspecified)',
			'',
			'Selected directions:',
			...branches.map(branch => `- ${branch.title}: ${branch.body}`),
		];
		return lines.join('\n');
	}

	private stepsFromSpec(spec: string): ArchitectStep[] {
		const lines = spec.split('\n').map(line => line.replace(/^[-*#\d.)\s]+/, '').trim()).filter(Boolean);
		const picked = lines.slice(0, 8);
		if (picked.length === 0) {
			picked.push('Review QKD assumptions', 'Map optical path', 'List security open questions');
		}
		return picked.map(title => ({
			id: newId('step'),
			title,
			body: '',
			done: false,
		}));
	}

	private notify(): void {
		for (const listener of this.listeners) {
			listener();
		}
	}
}

function categorize(rel: string): string {
	const text = rel.toLowerCase();
	if (/(attack|threat|security|eaves|adversar)/.test(text)) {
		return 'Threat model';
	}
	if (/(privacy|reconcil|key|post_process|kms)/.test(text)) {
		return 'Key processing';
	}
	if (/(node|fiber|optical|source|detector|station|channel|network)/.test(text)) {
		return 'Optical path';
	}
	if (/(manifest|readme|protocol|bbm92|qkd|shared\/taxonomy)/.test(text)) {
		return 'Protocol';
	}
	if (/(todo|open|assumption|question)/.test(text)) {
		return 'Open questions';
	}
	if (text.startsWith('nodes/') || text.startsWith('network/')) {
		return 'Optical path';
	}
	return 'Protocol';
}

async function readSnippet(uri: vscode.Uri): Promise<string> {
	try {
		const bytes = await vscode.workspace.fs.readFile(uri);
		return new TextDecoder().decode(bytes).slice(0, 420).trim();
	} catch {
		return '';
	}
}

function workspaceFolder(): vscode.WorkspaceFolder | undefined {
	return vscode.workspace.workspaceFolders?.[0];
}

function certiqsFile(...parts: string[]): vscode.Uri | undefined {
	const folder = workspaceFolder();
	return folder ? vscode.Uri.joinPath(folder.uri, '.certiqs', ...parts) : undefined;
}

async function ensureCertiqsFile(...parts: string[]): Promise<vscode.Uri> {
	const folder = workspaceFolder();
	if (!folder) {
		throw new Error('Open a workspace folder to store certiqs knowledge.');
	}
	const dirParts = parts.slice(0, -1);
	const dir = vscode.Uri.joinPath(folder.uri, '.certiqs', ...dirParts);
	await vscode.workspace.fs.createDirectory(dir);
	return vscode.Uri.joinPath(folder.uri, '.certiqs', ...parts);
}

async function pathExists(uri: vscode.Uri): Promise<boolean> {
	try {
		await vscode.workspace.fs.stat(uri);
		return true;
	} catch {
		return false;
	}
}

async function readJson<T>(uri: vscode.Uri): Promise<T> {
	const bytes = await vscode.workspace.fs.readFile(uri);
	return JSON.parse(new TextDecoder().decode(bytes)) as T;
}

async function writeJson(uri: vscode.Uri, value: unknown): Promise<void> {
	await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode(`${JSON.stringify(value, null, 2)}\n`));
}

function slugify(value: string): string {
	return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'spec';
}
