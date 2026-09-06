/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { SimClient } from './simClient';

export class SimTerminals implements vscode.Disposable {
	private api: vscode.Terminal | undefined;
	private apiWrite: vscode.EventEmitter<string> | undefined;
	private prompt: vscode.Terminal | undefined;
	private promptWrite: vscode.EventEmitter<string> | undefined;
	private promptBuffer = '';
	private runId: string | undefined;

	constructor(private readonly getClient: () => SimClient) { }

	setRunId(runId: string | undefined): void {
		this.runId = runId;
	}

	revealApi(command: string): void {
		if (!this.api || !this.apiWrite) {
			const write = new vscode.EventEmitter<string>();
			this.apiWrite = write;
			this.api = vscode.window.createTerminal({
				name: 'certiqs Sim API',
				pty: {
					onDidWrite: write.event,
					open: () => write.fire('\x1b[1mcertiqs Sim API\x1b[0m\r\n'),
					close: () => { },
				},
			});
		}
		this.apiWrite.fire(`$ ${command}\r\n`);
		this.api.show(true);
	}

	appendApi(text: string): void {
		const normalized = text.replace(/\r?\n/g, '\r\n');
		this.apiWrite?.fire(normalized.endsWith('\r\n') ? normalized : `${normalized}\r\n`);
	}

	revealPrompt(): void {
		if (!this.prompt || !this.promptWrite) {
			const write = new vscode.EventEmitter<string>();
			this.promptWrite = write;
			this.prompt = vscode.window.createTerminal({
				name: 'certiqs Sim Prompt',
				pty: {
					onDidWrite: write.event,
					open: () => {
						write.fire('\x1b[1mcertiqs Sim prompt\x1b[0m — type a command and press Enter.\r\n> ');
					},
					close: () => { },
					handleInput: (input: string) => {
						void this.onPromptInput(input);
					},
				},
			});
		}
		this.prompt.show(true);
	}

	dispose(): void {
		this.api?.dispose();
		this.prompt?.dispose();
		this.apiWrite?.dispose();
		this.promptWrite?.dispose();
	}

	private async onPromptInput(input: string): Promise<void> {
		if (input === '\r' || input === '\n') {
			const prompt = this.promptBuffer.trim();
			this.promptBuffer = '';
			this.promptWrite?.fire('\r\n');
			if (!prompt) {
				this.promptWrite?.fire('> ');
				return;
			}
			if (!this.runId) {
				this.promptWrite?.fire('no active run\r\n> ');
				return;
			}
			try {
				const result = await this.getClient().postSimTerminalPrompt(this.runId, prompt);
				const body = result.output || result.note || result.error || (result.ok ? 'ok' : 'failed');
				this.promptWrite?.fire(`${body.replace(/\r?\n/g, '\r\n')}\r\n> `);
			} catch (error) {
				this.promptWrite?.fire(`${(error as Error).message}\r\n> `);
			}
			return;
		}
		if (input === '\x7f') {
			if (this.promptBuffer) {
				this.promptBuffer = this.promptBuffer.slice(0, -1);
				this.promptWrite?.fire('\b \b');
			}
			return;
		}
		if (input.length === 1 && input >= ' ') {
			this.promptBuffer += input;
			this.promptWrite?.fire(input);
		}
	}
}
