/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HqPages } from './editorPanel';
import { HqHub } from './hqHub';
import { HqViewProvider, HQ_VIEW_ID } from './hqView';
import { SettingsViewProvider, SETTINGS_VIEW_ID } from './settingsView';

export function activate(context: vscode.ExtensionContext): void {
	let pages: HqPages;
	const hub = new HqHub({
		openLens: () => pages.openLens(),
		openSession: session => pages.openSession(session),
	});
	pages = new HqPages(context.extensionUri, hub);
	const hq = new HqViewProvider(context.extensionUri, hub);
	const settings = new SettingsViewProvider(context.extensionUri);

	context.subscriptions.push(
		hub,
		hub.store.watch(),
		hub.store.onDidChange(() => void hub.refresh()),
		pages,
		vscode.window.registerWebviewViewProvider(HQ_VIEW_ID, hq, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.window.registerWebviewViewProvider(SETTINGS_VIEW_ID, settings, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.commands.registerCommand('certiqs.hq.open', () => vscode.commands.executeCommand(`${HQ_VIEW_ID}.focus`)),
		vscode.commands.registerCommand('certiqs.hq.openSettings', () => vscode.commands.executeCommand(`${SETTINGS_VIEW_ID}.focus`)),
		vscode.commands.registerCommand('certiqs.hq.openContextLens', () => pages.openLens()),
		vscode.commands.registerCommand('certiqs.hq.newBrainstorming', () => hub.createAndOpen('brainstorm')),
		vscode.commands.registerCommand('certiqs.hq.newArchitect', () => hub.createAndOpen('architect')),
		vscode.commands.registerCommand('certiqs.hq.newChatSession', () => hub.createAndOpen('chat')),
		vscode.commands.registerCommand('certiqs.hq.restartExtensionHost', () => vscode.commands.executeCommand('workbench.action.restartExtensionHost')),
		watchRestartTrigger(context.extensionUri),
		vscode.workspace.onDidCreateFiles(() => void hq.refresh()),
		vscode.workspace.onDidDeleteFiles(() => void hq.refresh()),
		vscode.workspace.onDidChangeConfiguration(event => {
			if (event.affectsConfiguration('certiqs')) {
				void settings.refresh();
				void hq.refresh();
			}
		}),
	);

	void migrateDefaultTheme(context);
	void vscode.commands.executeCommand(`${HQ_VIEW_ID}.focus`);
}

export function deactivate(): void { }

function watchRestartTrigger(extensionUri: vscode.Uri): vscode.Disposable {
	const dir = vscode.Uri.joinPath(extensionUri, '..', '..', '.build', 'run-debug');
	const pattern = new vscode.RelativePattern(dir, 'restart-extension-host');
	const watcher = vscode.workspace.createFileSystemWatcher(pattern);
	let timer: ReturnType<typeof setTimeout> | undefined;
	const restart = () => {
		clearTimeout(timer);
		timer = setTimeout(() => {
			void vscode.commands.executeCommand('workbench.action.restartExtensionHost');
		}, 150);
	};
	void vscode.workspace.fs.createDirectory(dir);
	watcher.onDidCreate(restart);
	watcher.onDidChange(restart);
	return watcher;
}

async function migrateDefaultTheme(context: vscode.ExtensionContext): Promise<void> {
	if (context.globalState.get('certiqs.theme.migrated') === true) {
		return;
	}
	const inspected = vscode.workspace.getConfiguration('workbench').inspect<string>('colorTheme');
	const current = inspected?.globalValue ?? inspected?.workspaceValue;
	if (current === undefined || current === 'Dark 2026') {
		await vscode.workspace.getConfiguration('workbench').update('colorTheme', 'Certiqs Dark', vscode.ConfigurationTarget.Global);
	}
	await context.globalState.update('certiqs.theme.migrated', true);
}
