/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { KnowledgeStore } from './knowledgeStore';
import type { SessionKind, SessionFile } from './knowledgeTypes';
import { HostToWebview, HqSkill, HqState, PROCESS_LABELS, RpcMethod, WebviewToHost } from './protocol';
import { loadRuntimeCatalog, runRuntimeCommand } from './runtimeRegistry';

export type HqMessenger = {
	post(message: HostToWebview): Thenable<boolean> | undefined;
};

const SKILLS_DIR = ['.certiqs', 'skills'];

export class HqHub implements vscode.Disposable {
	readonly store = new KnowledgeStore();
	private readonly views = new Set<HqMessenger>();
	private readonly onOpenSession: (session: SessionFile) => void;
	private readonly onOpenLens: () => void;

	constructor(handlers: { openLens: () => void; openSession: (session: SessionFile) => void }) {
		this.onOpenLens = handlers.openLens;
		this.onOpenSession = handlers.openSession;
	}

	attach(messenger: HqMessenger): vscode.Disposable {
		this.views.add(messenger);
		void this.broadcastAll();
		return { dispose: () => this.views.delete(messenger) };
	}

	async handle(message: WebviewToHost): Promise<void> {
		switch (message.type) {
			case 'ready':
			case 'refresh':
				await this.broadcastAll();
				return;
			case 'readyRuntimes':
				await this.broadcastRuntimes();
				return;
			case 'runtimeAction':
				try {
					await runRuntimeCommand(message.sourceId, { type: message.action });
				} catch (error) {
					void vscode.window.showErrorMessage(`certiqs runtime: ${(error as Error).message}`);
				}
				await this.broadcastRuntimes();
				return;
			case 'openFixture':
				await vscode.commands.executeCommand('certiqs.assurance.openFixture');
				await this.broadcastState();
				return;
			case 'runSynthetic':
				await vscode.commands.executeCommand('certiqs.assurance.runSynthetic');
				await this.broadcastState();
				return;
			case 'exportResult':
				await vscode.commands.executeCommand('certiqs.assurance.exportResult');
				return;
			case 'openRecords':
				await vscode.commands.executeCommand('certiqs.assurance.records.focus');
				return;
			case 'editMcpJson':
				await this.openMcpJson();
				await this.broadcastState();
				return;
			case 'createSkill':
				await this.createSkill(message.slug);
				await this.broadcastState();
				return;
			case 'openContextLens':
				this.onOpenLens();
				return;
			case 'openSettings':
				await vscode.commands.executeCommand('certiqs.hq.openSettings');
				return;
			case 'newSession':
				await this.createAndOpen(message.kind);
				return;
			case 'openSession':
				await this.openSession(message.id);
				return;
			case 'archiveSession':
				await this.store.archiveSession(message.id);
				await this.broadcastAll();
				return;
			case 'rpc':
				await this.rpc(message.id, message.method, message.params ?? {});
				return;
		}
	}

	async refresh(): Promise<void> {
		await this.broadcastAll();
	}

	async createAndOpen(kind: SessionKind): Promise<SessionFile> {
		const session = await this.store.createSession(kind);
		this.onOpenSession(session);
		await this.broadcastAll();
		return session;
	}

	async openSession(id: string): Promise<void> {
		const session = await this.store.readSession(id);
		if (!session) {
			void vscode.window.showErrorMessage(`Session ${id} was not found.`);
			return;
		}
		this.store.setActiveSession(session.id);
		this.onOpenSession(session);
		await this.broadcastAll();
	}

	openLens(): void {
		this.onOpenLens();
	}

	dispose(): void {
		this.store.dispose();
		this.views.clear();
	}

	private async rpc(id: string, method: RpcMethod, params: Record<string, unknown>): Promise<void> {
		try {
			const result = await this.invoke(method, params);
			this.broadcast({ type: 'rpcResult', id, result });
			if (method !== 'getKnowledge' && method !== 'getSession') {
				await this.broadcastAll();
			}
		} catch (error) {
			this.broadcast({ type: 'rpcError', id, error: (error as Error).message });
		}
	}

	private async invoke(method: RpcMethod, params: Record<string, unknown>): Promise<unknown> {
		switch (method) {
			case 'getKnowledge':
				return this.store.snapshot();
			case 'setWikiStrategy':
				return this.store.setWikiStrategy(String(params.strategy) as 'all' | 'auto' | 'manual' | 'index');
			case 'addWikiFile':
				return this.store.addWikiFile(String(params.path ?? ''));
			case 'removeWikiFile':
				return this.store.removeWikiFile(String(params.path ?? ''));
			case 'toggleLoomHidden':
				return this.store.toggleLoomHidden(String(params.id ?? ''));
			case 'removeLoomEntry':
				return this.store.removeLoomEntry(String(params.id ?? ''));
			case 'initializeKnowledge':
				return this.store.initializeKnowledge();
			case 'reviewerAction':
				return { message: await this.store.reviewerAction(String(params.action ?? '')) };
			case 'getSession':
				return this.store.readSession(String(params.id ?? ''));
			case 'createSession': {
				const session = await this.store.createSession(String(params.kind) as SessionKind, params.title ? String(params.title) : undefined);
				this.onOpenSession(session);
				return session;
			}
			case 'openSession':
				await this.openSession(String(params.id ?? ''));
				return this.store.readSession(String(params.id ?? ''));
			case 'archiveSession':
				return this.store.archiveSession(String(params.id ?? ''), params.archived !== false);
			case 'appendMessage':
				return this.store.appendMessage(String(params.id ?? ''), String(params.text ?? ''), (params.role as 'user' | 'system' | 'note') ?? 'user');
			case 'updateSession':
				return this.store.updateSession(String(params.id ?? ''), (params.patch ?? {}) as Partial<SessionFile>);
			case 'approveSpec':
				return this.store.approveSpec(String(params.id ?? ''));
			case 'sendToArchitect': {
				const session = await this.store.sendToArchitect(String(params.id ?? ''));
				this.onOpenSession(session);
				return session;
			}
		}
	}

	private async broadcastAll(): Promise<void> {
		await this.broadcastState();
		await this.broadcastKnowledge();
		await this.broadcastRuntimes();
	}

	private async broadcastState(): Promise<void> {
		this.broadcast({ type: 'state', payload: await this.readState() });
	}

	private async broadcastKnowledge(): Promise<void> {
		this.broadcast({ type: 'knowledge', payload: await this.store.snapshot() });
	}

	private async broadcastRuntimes(): Promise<void> {
		this.broadcast({ type: 'runtimes', payload: await loadRuntimeCatalog() });
	}

	private broadcast(message: HostToWebview): void {
		for (const view of this.views) {
			void view.post(message);
		}
	}

	private async readState(): Promise<HqState> {
		return {
			fixtureLoaded: await pathExists(workspaceFile('synthetic-fixture.json')),
			skills: await listSkills(),
			mcpConfigured: await mcpConfigured(),
			labels: PROCESS_LABELS,
			notice: 'HQ does not call a model provider. Sessions persist locally under .certiqs.',
			knowledge: await this.store.snapshot(),
		};
	}

	private async openMcpJson(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			void vscode.window.showErrorMessage('Editing MCP config is denied in an untrusted workspace.');
			return;
		}
		const existing = workspaceFile('.vscode', 'mcp.json');
		if (existing && await pathExists(existing)) {
			await vscode.window.showTextDocument(existing);
			return;
		}
		try {
			await vscode.commands.executeCommand('workbench.mcp.openWorkspaceFolderMcpJson');
		} catch {
			const folder = vscode.workspace.workspaceFolders?.[0];
			if (!folder) {
				void vscode.window.showErrorMessage('Open a workspace folder to create .vscode/mcp.json.');
				return;
			}
			const dir = vscode.Uri.joinPath(folder.uri, '.vscode');
			await vscode.workspace.fs.createDirectory(dir);
			const uri = vscode.Uri.joinPath(dir, 'mcp.json');
			await vscode.workspace.fs.writeFile(uri, new TextEncoder().encode('{\n\t"servers": {}\n}\n'));
			await vscode.window.showTextDocument(uri);
		}
	}

	private async createSkill(rawSlug: string): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			void vscode.window.showErrorMessage('Creating a skill is denied in an untrusted workspace.');
			return;
		}
		const folder = vscode.workspace.workspaceFolders?.[0];
		if (!folder) {
			void vscode.window.showErrorMessage('Open a workspace folder to create a skill.');
			return;
		}
		const slug = rawSlug.trim().toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
		if (!slug) {
			void vscode.window.showErrorMessage('Skill slug must look like my-skill.');
			return;
		}
		const dir = vscode.Uri.joinPath(folder.uri, ...SKILLS_DIR, slug);
		const file = vscode.Uri.joinPath(dir, 'SKILL.md');
		if (await pathExists(file)) {
			await vscode.window.showTextDocument(file);
			return;
		}
		await vscode.workspace.fs.createDirectory(dir);
		await vscode.workspace.fs.writeFile(file, new TextEncoder().encode(`---\nname: ${slug}\n---\n\n# ${slug}\n\nLocal skill stub. This is not a published gallery entry.\n`));
		await vscode.window.showTextDocument(file);
	}
}

async function listSkills(): Promise<HqSkill[]> {
	const root = workspaceFile(...SKILLS_DIR);
	if (!root || !(await pathExists(root))) {
		return [];
	}
	const entries = await vscode.workspace.fs.readDirectory(root);
	const skills: HqSkill[] = [];
	for (const [name, type] of entries) {
		if (type !== vscode.FileType.Directory) {
			continue;
		}
		const file = vscode.Uri.joinPath(root, name, 'SKILL.md');
		if (await pathExists(file)) {
			skills.push({ slug: name, path: file.fsPath });
		}
	}
	return skills;
}

async function mcpConfigured(): Promise<boolean> {
	for (const uri of [workspaceFile('.vscode', 'mcp.json'), workspaceFile('.mcp.json')]) {
		if (await pathExists(uri)) {
			return true;
		}
	}
	return false;
}

function workspaceFile(...parts: string[]): vscode.Uri | undefined {
	const folder = vscode.workspace.workspaceFolders?.[0];
	return folder ? vscode.Uri.joinPath(folder.uri, ...parts) : undefined;
}

async function pathExists(uri: vscode.Uri | undefined): Promise<boolean> {
	if (!uri) {
		return false;
	}
	try {
		await vscode.workspace.fs.stat(uri);
		return true;
	} catch {
		return false;
	}
}
