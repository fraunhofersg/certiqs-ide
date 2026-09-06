/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import { envForChild, QdbEnv } from './credentials';
import { probeInterpreter } from './interpreters';

export type ProcessLogSink = {
	command: (command: string) => void;
	line: (line: string) => void;
};

export class PythonRuntime implements vscode.Disposable {
	private process: ChildProcess | undefined;
	private starting: Promise<void> | undefined;
	private processLog: ProcessLogSink | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly output: vscode.OutputChannel,
		private readonly loadEnv: () => Promise<QdbEnv>,
	) { }

	attachProcessLog(sink: ProcessLogSink): void {
		this.processLog = sink;
	}

	hasTrackedProcess(): boolean {
		return Boolean(this.process && this.process.exitCode === null);
	}

	get pythonRoot(): string {
		return path.join(this.extensionUri.fsPath, 'python');
	}

	get port(): number {
		return vscode.workspace.getConfiguration('certiqs.qdb').get<number>('port', 8012);
	}

	get pythonPath(): string {
		const configured = vscode.workspace.getConfiguration('certiqs.qdb').get<string>('pythonPath', 'python3');
		if (configured !== 'python3') {
			return configured;
		}
		const bundled = path.join(this.pythonRoot, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
		return probeInterpreter(bundled)?.path ?? configured;
	}

	get origin(): string {
		return `http://127.0.0.1:${this.port}`;
	}

	async health(): Promise<boolean> {
		try {
			const res = await fetch(`${this.origin}/health`);
			if (!res.ok) {
				return false;
			}
			const body = await res.json() as { status?: string };
			return body.status === 'ok';
		} catch {
			return false;
		}
	}

	async ensureStarted(): Promise<void> {
		if (this.hasTrackedProcess() && await this.health()) {
			return;
		}
		if (await this.health()) {
			throw new Error(`Port ${this.port} is already in use by a process this extension does not own.`);
		}
		if (!this.starting) {
			this.starting = this.spawnApi().finally(() => {
				this.starting = undefined;
			});
		}
		await this.starting;
	}

	async stop(): Promise<void> {
		const child = this.process;
		this.process = undefined;
		if (!child || child.killed || child.exitCode !== null) {
			return;
		}
		child.kill('SIGTERM');
		await new Promise<void>(resolve => {
			const timer = setTimeout(() => {
				if (child.exitCode === null) {
					child.kill('SIGKILL');
				}
				resolve();
			}, 2000);
			child.once('exit', () => {
				clearTimeout(timer);
				resolve();
			});
		});
	}

	showOutput(): void {
		this.output.show(true);
	}

	dispose(): void {
		void this.stop();
	}

	private async spawnApi(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			throw new Error('Starting the QDB API is denied in an untrusted workspace.');
		}
		const env = await this.loadEnv();
		if (!env.databaseUrl) {
			throw new Error('DATABASE_URL is not set. Open certiqs Settings → QDB and store the Postgres URL.');
		}
		await this.ensureDeps();
		const python = this.pythonPath;
		const childEnv = {
			...process.env,
			...envForChild(env),
			PYTHONUNBUFFERED: '1',
		};
		const args = ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(this.port)];
		const command = `${python} ${args.join(' ')}`;
		this.output.appendLine(`$ ${command}`);
		this.processLog?.command(command);

		const child = spawn(python, args, {
			cwd: this.pythonRoot,
			env: childEnv,
			stdio: ['ignore', 'pipe', 'pipe'],
		});
		this.process = child;
		child.stdout?.on('data', chunk => this.appendProcess(String(chunk)));
		child.stderr?.on('data', chunk => this.appendProcess(String(chunk)));
		child.on('exit', (code, signal) => {
			this.output.appendLine(`api exited code=${code} signal=${signal ?? ''}`);
			if (this.process === child) {
				this.process = undefined;
			}
		});
		child.on('error', error => {
			this.output.appendLine(error.message);
		});

		const deadline = Date.now() + 20_000;
		while (Date.now() < deadline) {
			if (child.exitCode !== null) {
				throw new Error(`QDB API exited before it became ready (code ${child.exitCode}). See the certiqs QDB output channel.`);
			}
			if (await this.health()) {
				this.output.appendLine('api ready');
				return;
			}
			await delay(300);
		}
		throw new Error(`QDB API did not become ready on ${this.origin}.`);
	}

	private async ensureDeps(): Promise<void> {
		const probe = await this.capturePython(['-c', 'import fastapi, uvicorn, asyncpg, jwt, pydantic_settings']);
		if (probe.code === 0) {
			return;
		}
		this.output.appendLine('installing python requirements');
		const requirements = path.join(this.pythonRoot, 'requirements.txt');
		const result = await this.capturePython(['-m', 'pip', 'install', '-r', requirements], { log: true, timeoutMs: 180_000 });
		if (result.code !== 0) {
			throw new Error(`pip install failed (code ${result.code}). See the certiqs QDB output channel.`);
		}
	}

	private capturePython(args: string[], options?: { timeoutMs?: number; log?: boolean }): Promise<{ code: number; stdout: string; stderr: string }> {
		return new Promise(resolve => {
			const child = spawn(this.pythonPath, args, {
				cwd: this.pythonRoot,
				env: process.env,
				stdio: ['ignore', 'pipe', 'pipe'],
			});
			let stdout = '';
			let stderr = '';
			child.stdout?.on('data', chunk => {
				const text = String(chunk);
				stdout += text;
				if (options?.log) {
					this.output.append(text);
				}
			});
			child.stderr?.on('data', chunk => {
				const text = String(chunk);
				stderr += text;
				if (options?.log) {
					this.output.append(text);
				}
			});
			const timer = setTimeout(() => child.kill('SIGKILL'), options?.timeoutMs ?? 20_000);
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

	private appendProcess(text: string): void {
		this.output.append(text);
		this.processLog?.line(text.replace(/\r?\n$/, ''));
	}
}

function delay(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}
