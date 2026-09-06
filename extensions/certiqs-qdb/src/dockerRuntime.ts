/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { spawn } from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import { envForChild, QdbEnv } from './credentials';
import { ProcessLogSink } from './pythonRuntime';

export const QDB_CONTAINER_NAME = 'certiqs-qdb-api';
export const DEFAULT_QDB_IMAGE = 'certiqs-qdb:local';

export class DockerRuntime implements vscode.Disposable {
	private processLog: ProcessLogSink | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly output: vscode.OutputChannel,
		private readonly loadEnv: () => Promise<QdbEnv>,
	) { }

	attachProcessLog(sink: ProcessLogSink): void {
		this.processLog = sink;
	}

	get port(): number {
		return vscode.workspace.getConfiguration('certiqs.qdb').get<number>('port', 8012);
	}

	get image(): string {
		return vscode.workspace.getConfiguration('certiqs.qdb').get<string>('dockerImage', '') || DEFAULT_QDB_IMAGE;
	}

	get origin(): string {
		return `http://127.0.0.1:${this.port}`;
	}

	async available(): Promise<boolean> {
		const result = await this.run(['version', '--format', '{{.Server.Version}}'], 4000);
		return result.code === 0;
	}

	async health(): Promise<boolean> {
		try {
			const res = await fetch(`${this.origin}/health`);
			return res.ok;
		} catch {
			return false;
		}
	}

	async ensureStarted(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			throw new Error('Starting the QDB API is denied in an untrusted workspace.');
		}
		if (!(await this.available())) {
			throw new Error('Docker is not available.');
		}
		const env = await this.loadEnv();
		if (!env.databaseUrl) {
			throw new Error('DATABASE_URL is not set. Open certiqs Settings → QDB and store the Postgres URL.');
		}
		if (!(await this.imageExists())) {
			await this.rebuild();
		}
		await this.stop();
		const childEnv = envForChild(env);
		const args = [
			'run', '-d', '--rm',
			'--name', QDB_CONTAINER_NAME,
			'-p', `127.0.0.1:${this.port}:8012`,
		];
		for (const [key, value] of Object.entries(childEnv)) {
			if (value) {
				args.push('-e', `${key}=${value}`);
			}
		}
		args.push(this.image);
		const result = await this.run(args, 60_000, true);
		if (result.code !== 0) {
			throw new Error(`docker run failed: ${result.stderr || result.stdout}`);
		}
		const deadline = Date.now() + 20_000;
		while (Date.now() < deadline) {
			if (await this.health()) {
				this.output.appendLine('docker api ready');
				return;
			}
			await delay(400);
		}
		throw new Error(`QDB Docker API did not become ready on ${this.origin}.`);
	}

	async stop(): Promise<void> {
		await this.run(['rm', '-f', QDB_CONTAINER_NAME], 10_000);
	}

	async inspect(): Promise<{ available: boolean; status?: string; containerId?: string }> {
		const available = await this.available();
		if (!available) {
			return { available };
		}
		const result = await this.run(['inspect', '-f', '{{.Id}} {{.State.Status}}', QDB_CONTAINER_NAME], 4000);
		if (result.code !== 0) {
			return { available, status: 'stopped' };
		}
		const [containerId, status] = result.stdout.trim().split(/\s+/);
		return { available, containerId, status };
	}

	async rebuild(): Promise<void> {
		const dockerfile = path.join(this.extensionUri.fsPath, 'docker', 'Dockerfile');
		const args = ['build', '-t', this.image, '-f', dockerfile, this.extensionUri.fsPath];
		this.output.appendLine(`$ docker ${args.join(' ')}`);
		const result = await this.run(args, 300_000, true);
		if (result.code !== 0) {
			throw new Error(`docker build failed (code ${result.code}). See the certiqs QDB output channel.`);
		}
	}

	dispose(): void {
		void this.stop();
	}

	private async imageExists(): Promise<boolean> {
		const result = await this.run(['image', 'inspect', this.image], 4000);
		return result.code === 0;
	}

	private run(args: string[], timeoutMs: number, log = false): Promise<{ code: number; stdout: string; stderr: string }> {
		return new Promise(resolve => {
			const child = spawn('docker', args, { stdio: ['ignore', 'pipe', 'pipe'] });
			this.processLog?.command(`docker ${args.join(' ')}`);
			let stdout = '';
			let stderr = '';
			child.stdout?.on('data', chunk => {
				const text = String(chunk);
				stdout += text;
				if (log) {
					this.output.append(text);
				}
			});
			child.stderr?.on('data', chunk => {
				const text = String(chunk);
				stderr += text;
				if (log) {
					this.output.append(text);
				}
			});
			const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs);
			child.on('error', error => {
				clearTimeout(timer);
				resolve({ code: 1, stdout, stderr: error.message });
			});
			child.on('exit', code => {
				clearTimeout(timer);
				resolve({ code: code ?? 1, stdout, stderr });
			});
		});
	}
}

function delay(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}
