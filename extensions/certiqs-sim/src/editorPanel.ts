/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { SimSurface, renderSimHtml } from './webviewHtml';
import { SimMessenger, SimSession } from './simSession';
import { HostToWebview } from './protocol';

export class SimEditorPanel implements vscode.Disposable {
	private panel: vscode.WebviewPanel | undefined;
	private attached: vscode.Disposable | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly session: SimSession,
		private readonly viewType: string,
		private readonly title: string,
		private readonly surface: SimSurface,
		private readonly column: vscode.ViewColumn = vscode.ViewColumn.One,
	) { }

	show(): void {
		if (this.panel) {
			this.panel.reveal(this.column, true);
			void this.session.broadcastState();
			return;
		}
		this.panel = vscode.window.createWebviewPanel(
			this.viewType,
			this.title,
			{ viewColumn: this.column, preserveFocus: true },
			{
				enableScripts: true,
				enableFindWidget: true,
				retainContextWhenHidden: true,
				localResourceRoots: [
					vscode.Uri.joinPath(this.extensionUri, 'media'),
					vscode.Uri.joinPath(this.extensionUri, 'icons'),
				],
			},
		);
		this.session.setIconBase(
			this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'icons')).toString(),
		);
		this.panel.webview.html = renderSimHtml(this.panel.webview, this.extensionUri, this.surface);
		this.attached = this.session.attach(this.messenger());
		this.panel.webview.onDidReceiveMessage(message => {
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

	private messenger(): SimMessenger {
		return {
			post: (message: HostToWebview) => this.panel?.webview.postMessage(message),
		};
	}
}
