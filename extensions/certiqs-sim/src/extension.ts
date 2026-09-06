/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { handleRuntimeCommand } from './runtime/handler';
import { RuntimeCommand } from './runtime/types';
import { handleSettingsCommand, SettingsCommand } from './settings/handler';
import { ServiceRuntime } from './serviceRuntime';
import { SimSession } from './simSession';
import { SimViewProvider, SIM_VIEW_ID } from './simView';
import { SimPages } from './welcomeView';

export function activate(context: vscode.ExtensionContext): void {
	const runtime = new ServiceRuntime(context.extensionUri);
	const session = new SimSession(runtime);
	const pages = new SimPages(context.extensionUri, session);
	const provider = new SimViewProvider(context.extensionUri, session, () => pages.overview.show());
	context.subscriptions.push(
		runtime,
		session,
		pages,
		vscode.window.registerWebviewViewProvider(SIM_VIEW_ID, provider, {
			webviewOptions: { retainContextWhenHidden: true },
		}),
		vscode.commands.registerCommand('certiqs.sim.open', async () => {
			await vscode.commands.executeCommand(`${SIM_VIEW_ID}.focus`);
			pages.overview.show();
		}),
		vscode.commands.registerCommand('certiqs.sim.openWelcome', () => pages.overview.show()),
		vscode.commands.registerCommand('certiqs.sim.openDashboard', () => pages.dashboard.show()),
		vscode.commands.registerCommand('certiqs.sim.openSystem', () => pages.system.show()),
		vscode.commands.registerCommand('certiqs.sim.showPrompt', () => session.terminals.revealPrompt()),
		vscode.commands.registerCommand('certiqs.sim.startApi', async () => {
			await session.startApi();
		}),
		vscode.commands.registerCommand('certiqs.sim.stopApi', async () => {
			await runtime.stop();
			await session.broadcastState();
		}),
		vscode.commands.registerCommand('certiqs.sim.showLog', () => session.logs.showProcess()),
		vscode.commands.registerCommand('certiqs.sim.settings', (command: SettingsCommand) => handleSettingsCommand(context, runtime, command)),
		vscode.commands.registerCommand('certiqs.sim.runtime', (command: RuntimeCommand) => handleRuntimeCommand(runtime, command)),
		vscode.commands.registerCommand('certiqs.sim.installEngine', async () => {
			await handleSettingsCommand(context, runtime, { type: 'action', id: 'installEngine' });
		}),
	);
}

export function deactivate(): void { }
