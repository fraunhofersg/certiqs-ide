/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { HostToWebview, QdbSurface, WebviewToHost } from './protocol';
import { QdbMessenger, QdbSession } from './qdbSession';
import { renderQdbHtml } from './webviewHtml';

export class QdbEditorPanel implements vscode.Disposable {
	private panel: vscode.WebviewPanel | undefined;
	private attached: vscode.Disposable | undefined;
	private systemId: number | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly session: QdbSession,
		private readonly viewType: string,
		private readonly title: string,
		private readonly surface: QdbSurface,
		private readonly column: vscode.ViewColumn = vscode.ViewColumn.One,
	) { }

	show(systemId?: number): void {
		if (typeof systemId === 'number') {
			this.systemId = systemId;
		}
		if (this.panel) {
			this.panel.reveal(this.column, true);
			this.panel.webview.html = renderQdbHtml(this.panel.webview, this.extensionUri, this.surface, {
				isAdmin: this.session.isAdmin,
				systemId: this.systemId ?? this.session.selectedSystemId,
			});
			void this.session.broadcastState();
			return;
		}
		this.panel = vscode.window.createWebviewPanel(
			this.viewType,
			this.titleFor(),
			{ viewColumn: this.column, preserveFocus: true },
			{
				enableScripts: true,
				enableFindWidget: true,
				retainContextWhenHidden: true,
				localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')],
			},
		);
		this.panel.webview.html = renderQdbHtml(this.panel.webview, this.extensionUri, this.surface, {
			isAdmin: this.session.isAdmin,
			systemId: this.systemId ?? this.session.selectedSystemId,
		});
		this.attached = this.session.attach(this.messenger());
		this.panel.webview.onDidReceiveMessage((message: WebviewToHost) => {
			void this.session.handle(message);
		});
		this.panel.onDidDispose(() => {
			this.attached?.dispose();
			this.attached = undefined;
			this.panel = undefined;
		});
		void this.session.broadcastState();
	}

	dispose(): void {
		this.attached?.dispose();
		this.panel?.dispose();
	}

	private titleFor(): string {
		if (this.surface === 'system' && this.systemId) {
			return `QDB System ${this.systemId}`;
		}
		return this.title;
	}

	private messenger(): QdbMessenger {
		return {
			post: (message: HostToWebview) => this.panel?.webview.postMessage(message),
		};
	}
}
