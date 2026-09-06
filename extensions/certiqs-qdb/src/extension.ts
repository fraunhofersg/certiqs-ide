/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { QdbPages } from './pages';
import { QdbSession } from './qdbSession';
import { QDB_INSPECTOR_ID, QDB_VIEW_ID, QdbViewProvider } from './qdbView';
import { handleRuntimeCommand } from './runtime/handler';
import { RuntimeCommand } from './runtime/types';
import { ServiceRuntime } from './serviceRuntime';
import { handleSettingsCommand, SettingsCommand } from './settings/handler';

export function activate(context: vscode.ExtensionContext): void {
	const runtime = new ServiceRuntime(context);
	const session = new QdbSession(context, runtime);
	const pages = new QdbPages(context.extensionUri, session);
	const explorer = new QdbViewProvider(context.extensionUri, session, 'sidebar', () => pages.hub.show());
	const inspector = new QdbViewProvider(context.extensionUri, session, 'inspector');
	context.subscriptions.push(
		runtime,
		session,
		pages,
		vscode.window.registerWebviewViewProvider(QDB_VIEW_ID, explorer, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.window.registerWebviewViewProvider(QDB_INSPECTOR_ID, inspector, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.commands.registerCommand('certiqs.qdb.open', async () => {
			await vscode.commands.executeCommand(`${QDB_VIEW_ID}.focus`);
			pages.hub.show();
		}),
		vscode.commands.registerCommand('certiqs.qdb.openHub', () => pages.hub.show()),
		vscode.commands.registerCommand('certiqs.qdb.openSystems', () => pages.systems.show()),
		vscode.commands.registerCommand('certiqs.qdb.openWizard', () => pages.wizard.show()),
		vscode.commands.registerCommand('certiqs.qdb.openSystem', (systemId?: number) => pages.system.show(systemId)),
		vscode.commands.registerCommand('certiqs.qdb.openApplicability', (systemId?: number) => pages.applicability.show(systemId)),
		vscode.commands.registerCommand('certiqs.qdb.openSearch', () => pages.search.show()),
		vscode.commands.registerCommand('certiqs.qdb.openVulnerabilities', () => pages.vulnerabilities.show()),
		vscode.commands.registerCommand('certiqs.qdb.openEAs', () => pages.eas.show()),
		vscode.commands.registerCommand('certiqs.qdb.openCountermeasures', () => pages.countermeasures.show()),
		vscode.commands.registerCommand('certiqs.qdb.openDocuments', () => pages.documents.show()),
		vscode.commands.registerCommand('certiqs.qdb.startApi', () => session.startApi()),
		vscode.commands.registerCommand('certiqs.qdb.stopApi', async () => {
			await runtime.stop();
			await session.broadcastState();
		}),
		vscode.commands.registerCommand('certiqs.qdb.showLog', () => runtime.showOutput()),
		vscode.commands.registerCommand('certiqs.qdb.settings', (command: SettingsCommand) => handleSettingsCommand(context, runtime, command)),
		vscode.commands.registerCommand('certiqs.qdb.runtime', (command: RuntimeCommand) => handleRuntimeCommand(runtime, command)),
	);
}

export function deactivate(): void { }
