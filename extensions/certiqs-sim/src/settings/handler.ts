/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { NETSQUID_PASSWORD_KEY, installEngine } from '../engineSettings';
import { listInterpreters, probeInterpreter } from '../interpreters';
import { ServiceRuntime } from '../serviceRuntime';

export type SettingsCommand =
	| { type: 'describe' }
	| { type: 'get' }
	| { type: 'set'; values?: Record<string, unknown>; secrets?: Record<string, string>; clearSecrets?: string[] }
	| { type: 'action'; id: string };

type SettingsField = {
	kind: string;
	id: string;
	setting?: string;
	secretKey?: string;
};

type SettingsManifest = {
	id: string;
	title: string;
	order?: number;
	sections: { id: string; fields: SettingsField[] }[];
};

export async function handleSettingsCommand(
	context: vscode.ExtensionContext,
	runtime: ServiceRuntime,
	command: SettingsCommand,
): Promise<unknown> {
	if (!command?.type) {
		return;
	}
	const manifest = await readManifest(context.extensionUri);
	switch (command.type) {
		case 'describe':
			return manifest;
		case 'get':
			return readSnapshot(context, runtime, manifest);
		case 'set':
			await applyPatch(context, manifest, command.values ?? {}, command.secrets, command.clearSecrets);
			return readSnapshot(context, runtime, manifest);
		case 'action':
			await runAction(context, runtime, command.id);
			return readSnapshot(context, runtime, manifest);
	}
}

async function readManifest(extensionUri: vscode.Uri): Promise<SettingsManifest> {
	const uri = vscode.Uri.joinPath(extensionUri, 'settings.json');
	const raw = await vscode.workspace.fs.readFile(uri);
	return JSON.parse(new TextDecoder().decode(raw)) as SettingsManifest;
}

async function readSnapshot(context: vscode.ExtensionContext, runtime: ServiceRuntime, manifest: SettingsManifest) {
	const values: Record<string, string | number | boolean> = {};
	const secretSet: Record<string, boolean> = {};
	for (const field of fieldsOf(manifest)) {
		if (field.setting) {
			const [section, key] = splitSetting(field.setting);
			const current = vscode.workspace.getConfiguration(section).get(key);
			if (typeof current === 'string' || typeof current === 'number' || typeof current === 'boolean') {
				values[field.id] = current;
			}
		}
		if (field.kind === 'secret' && field.secretKey) {
			secretSet[field.id] = Boolean(await context.secrets.get(field.secretKey));
		}
	}
	const passwordSet = Boolean(await context.secrets.get(NETSQUID_PASSWORD_KEY));
	const snapshot = await runtime.snapshot();
	const engine = await runtime.inspectEngine();
	const configured = String(values.pythonPath ?? 'python3');
	const interpreters = listInterpreters(runtime.local.pythonRoot, configured);
	const selected = probeInterpreter(runtime.pythonPath) ?? probeInterpreter(configured) ?? interpreters.find(item => item.path === configured);
	if (selected) {
		values.pythonPath = selected.path;
	}
	const mismatch = selected && !selected.compatible
		? `Python ${selected.version} mismatch — NetSquid needs 3.8–3.11`
		: !selected && configured
			? 'Interpreter not found — check the path'
			: '';
	return {
		values,
		secretSet,
		interpreters,
		status: {
			engineInstalled: engine.installed ? 'NetSquid installed' : 'NetSquid not installed',
			engineVersion: engine.version ? `Version ${engine.version}` : 'Version —',
			engineArch: `${engine.platform} ${engine.machine} · Python ${engine.pythonVersion}`,
			pythonMismatch: mismatch,
			passwordSet: passwordSet ? 'Password stored' : 'No password stored',
			dockerAvailable: snapshot.docker?.available ? 'Docker available' : 'Docker not installed',
			container: snapshot.docker?.status
				? `Container: ${snapshot.docker.status}${snapshot.docker.containerId ? ` ${snapshot.docker.containerId.slice(0, 12)}` : ''}`
				: 'Container: stopped',
			api: snapshot.state === 'ready'
				? `API: ready on :${runtime.port}`
				: snapshot.reason ?? `API: ${snapshot.state}`,
		},
	};
}

async function applyPatch(
	context: vscode.ExtensionContext,
	manifest: SettingsManifest,
	values: Record<string, unknown>,
	secrets: Record<string, string> | undefined,
	clearSecrets: string[] | undefined,
): Promise<void> {
	const byId = new Map(fieldsOf(manifest).map(field => [field.id, field]));
	for (const [id, value] of Object.entries(values)) {
		const field = byId.get(id);
		if (!field?.setting) {
			continue;
		}
		const [section, key] = splitSetting(field.setting);
		await vscode.workspace.getConfiguration(section).update(key, normalize(value, field.kind), vscode.ConfigurationTarget.Global);
	}
	for (const [id, value] of Object.entries(secrets ?? {})) {
		const field = byId.get(id);
		if (field?.secretKey && value.trim()) {
			await context.secrets.store(field.secretKey, value);
		}
	}
	for (const id of clearSecrets ?? []) {
		const field = byId.get(id);
		if (field?.secretKey) {
			await context.secrets.delete(field.secretKey);
		}
	}
}

async function runAction(context: vscode.ExtensionContext, runtime: ServiceRuntime, id: string): Promise<void> {
	if (id === 'runDebug') {
		runRepoScript(context.extensionUri, 'scripts/run-debug.sh');
		return;
	}
	if (id === 'refreshExtensions') {
		runRepoScript(context.extensionUri, 'scripts/refresh-extensions.sh', ['sim']);
		return;
	}
	if (id === 'rebuild') {
		await runtime.rebuild();
		void vscode.window.showInformationMessage('Sim image rebuild finished. See the certiqs Sim output channel.');
		return;
	}
	if (id === 'installEngine') {
		await installEngine(context, runtime);
		void vscode.window.showInformationMessage('NetSquid install finished. See the certiqs Sim output channel.');
		return;
	}
	if (id.startsWith('clearSecret:')) {
		const secretId = id.slice('clearSecret:'.length);
		const manifest = await readManifest(context.extensionUri);
		const field = fieldsOf(manifest).find(item => item.id === secretId);
		if (field?.secretKey) {
			await context.secrets.delete(field.secretKey);
		}
	}
}

function runRepoScript(extensionUri: vscode.Uri, relative: string, args: string[] = []): void {
	const root = vscode.Uri.joinPath(extensionUri, '..', '..').fsPath;
	const existing = vscode.window.terminals.find(terminal => terminal.name === 'certiqs IDE');
	const terminal = existing ?? vscode.window.createTerminal({ name: 'certiqs IDE', cwd: root });
	terminal.show();
	const command = [relative, ...args].map(part => (/[^A-Za-z0-9./_-]/.test(part) ? JSON.stringify(part) : part)).join(' ');
	terminal.sendText(`./${command}`);
}

function fieldsOf(manifest: SettingsManifest): SettingsField[] {
	return manifest.sections.flatMap(section => section.fields);
}

function splitSetting(setting: string): [string, string] {
	const index = setting.lastIndexOf('.');
	return [setting.slice(0, index), setting.slice(index + 1)];
}

function normalize(value: unknown, kind: string): string | number | boolean {
	if (kind === 'number') {
		return Number(value) || 0;
	}
	if (kind === 'toggle') {
		return Boolean(value);
	}
	return String(value ?? '').trim();
}
