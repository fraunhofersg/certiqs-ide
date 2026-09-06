/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { SimEditorPanel } from './editorPanel';
import { SimSession } from './simSession';

export const WELCOME_VIEW_TYPE = 'certiqs.sim.welcome';
export const DASHBOARD_VIEW_TYPE = 'certiqs.sim.dashboard';
export const SYSTEM_VIEW_TYPE = 'certiqs.sim.system';

export class SimPages implements vscode.Disposable {
	readonly overview: SimEditorPanel;
	readonly dashboard: SimEditorPanel;
	readonly system: SimEditorPanel;

	constructor(extensionUri: vscode.Uri, session: SimSession) {
		this.overview = new SimEditorPanel(extensionUri, session, WELCOME_VIEW_TYPE, 'certiqs Sim', 'overview');
		this.dashboard = new SimEditorPanel(extensionUri, session, DASHBOARD_VIEW_TYPE, 'Sim Dashboard', 'dashboard', vscode.ViewColumn.Two);
		this.system = new SimEditorPanel(extensionUri, session, SYSTEM_VIEW_TYPE, 'Sim System', 'system', vscode.ViewColumn.Two);
	}

	dispose(): void {
		this.overview.dispose();
		this.dashboard.dispose();
		this.system.dispose();
	}
}
