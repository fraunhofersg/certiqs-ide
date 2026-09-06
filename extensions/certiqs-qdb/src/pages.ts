/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { QdbEditorPanel } from './editorPanel';
import { QdbSession } from './qdbSession';

export class QdbPages implements vscode.Disposable {
	readonly hub: QdbEditorPanel;
	readonly systems: QdbEditorPanel;
	readonly wizard: QdbEditorPanel;
	readonly system: QdbEditorPanel;
	readonly applicability: QdbEditorPanel;
	readonly search: QdbEditorPanel;
	readonly vulnerabilities: QdbEditorPanel;
	readonly eas: QdbEditorPanel;
	readonly countermeasures: QdbEditorPanel;
	readonly documents: QdbEditorPanel;

	constructor(extensionUri: vscode.Uri, session: QdbSession) {
		this.hub = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.hub', 'certiqs QDB', 'hub');
		this.systems = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.systems', 'QDB Systems', 'systems');
		this.wizard = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.wizard', 'New QDB System', 'wizard');
		this.system = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.system', 'QDB System', 'system', vscode.ViewColumn.One);
		this.applicability = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.applicability', 'QDB Applicability', 'applicability', vscode.ViewColumn.One);
		this.search = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.search', 'QDB Search', 'search');
		this.vulnerabilities = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.vulnerabilities', 'QDB Attacks', 'vulnerabilities');
		this.eas = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.eas', 'QDB Evaluation Activities', 'eas');
		this.countermeasures = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.countermeasures', 'QDB Countermeasures', 'countermeasures');
		this.documents = new QdbEditorPanel(extensionUri, session, 'certiqs.qdb.documents', 'QDB Document Sources', 'documents');
	}

	dispose(): void {
		this.hub.dispose();
		this.systems.dispose();
		this.wizard.dispose();
		this.system.dispose();
		this.applicability.dispose();
		this.search.dispose();
		this.vulnerabilities.dispose();
		this.eas.dispose();
		this.countermeasures.dispose();
		this.documents.dispose();
	}
}
