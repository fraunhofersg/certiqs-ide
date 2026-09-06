/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import { probeInterpreter } from './interpreters';
import { SimClient } from './simClient';

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
		private readonly log: (line: string) => void = () => { },
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
		return vscode.workspace.getConfiguration('certiqs.sim').get<number>('port', 8011);
	}

	get pythonPath(): string {
		const configured = vscode.workspace.getConfiguration('certiqs.sim').get<string>('pythonPath', 'python3');
		if (configured !== 'python3') {
			return configured;
		}
		const exe = process.platform === 'win32' ? 'python.exe' : 'python';
		const candidates = [
			path.join(this.pythonRoot, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'),
			path.join(process.env.CONDA_PREFIX ?? '', '..', 'certiqs-sim', 'bin', exe),
			'/opt/anaconda3/envs/certiqs-sim/bin/python',
			'/opt/miniconda3/envs/certiqs-sim/bin/python',
			'python3.11',
			'python3.10',
		];
		for (const candidate of candidates) {
			const info = probeInterpreter(candidate);
			if (info?.compatible) {
				return info.path;
			}
		}
		return configured;
	}

	get client(): SimClient {
		return new SimClient(this.port);
	}

	async ensureStarted(): Promise<void> {
		if (this.hasTrackedProcess() && await this.client.health()) {
			return;
		}
		if (await this.client.health()) {
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

	appendLog(line: string): void {
		this.output.appendLine(line);
		this.output.show(true);
	}

	async hasEngine(): Promise<boolean> {
		return (await this.inspectEngine()).installed;
	}

	async inspectEngine(): Promise<EngineInfo> {
		const python = await this.capturePython([
			'-c',
			'import platform,sys; print(sys.version.split()[0]); print(sys.platform); print(platform.machine())',
		]);
		const [pythonVersion, platformName, machine] = python.stdout.trim().split(/\r?\n/);
		const info: EngineInfo = {
			installed: false,
			pythonVersion: pythonVersion || 'unknown',
			platform: platformName || process.platform,
			machine: machine || process.arch,
		};
		if (python.code !== 0) {
			return info;
		}
		const engine = await this.capturePython(['-c', 'import netsquid; print(netsquid.__version__)']);
		if (engine.code === 0 && engine.stdout.trim()) {
			info.installed = true;
			info.version = engine.stdout.trim().split(/\r?\n/)[0];
		}
		return info;
	}

	async latestNetsquidVersion(extraIndexUrl: string): Promise<string | undefined> {
		const result = await this.capturePython([
			'-m', 'pip', 'index', 'versions', 'netsquid',
			'--extra-index-url', extraIndexUrl,
			'--trusted-host', 'pypi.netsquid.org',
		]);
		this.output.append(redactIndex(result.stdout + result.stderr));
		const match = `${result.stdout}\n${result.stderr}`.match(/netsquid \(([^)]+)\)/i);
		return match?.[1]?.trim();
	}

	async installPackage(spec: string, extraIndexUrl: string): Promise<void> {
		this.output.appendLine(`$ ${this.pythonPath} -m pip install --upgrade ${spec} --extra-index-url https://pypi.netsquid.org --trusted-host pypi.netsquid.org`);
		this.output.show(true);
		const env = { ...process.env };
		delete env.PIP_EXTRA_INDEX_URL;
		const result = await this.capturePython([
			'-m', 'pip', 'install', '--upgrade', spec,
			'--extra-index-url', extraIndexUrl,
			'--trusted-host', 'pypi.netsquid.org',
		], { extraEnv: env, timeoutMs: 180_000, log: true });
		if (result.code !== 0) {
			throw new Error(`pip exited with code ${result.code}. See the certiqs Sim output channel.`);
		}
		this.output.appendLine('engine install finished');
	}

	private capturePython(args: string[], options?: { extraEnv?: NodeJS.ProcessEnv; timeoutMs?: number; log?: boolean }): Promise<{ code: number; stdout: string; stderr: string }> {
		return new Promise(resolve => {
			const child = spawn(this.pythonPath, args, {
				cwd: this.pythonRoot,
				env: { ...process.env, ...options?.extraEnv },
				stdio: ['ignore', 'pipe', 'pipe'],
			});
			let stdout = '';
			let stderr = '';
			child.stdout?.on('data', chunk => {
				const text = String(chunk);
				stdout += text;
				if (options?.log) {
					this.output.append(redactIndex(text));
				}
			});
			child.stderr?.on('data', chunk => {
				const text = String(chunk);
				stderr += text;
				if (options?.log) {
					this.output.append(redactIndex(text));
				}
			});
			const timer = setTimeout(() => {
				child.kill('SIGKILL');
			}, options?.timeoutMs ?? 20_000);
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

	dispose(): void {
		void this.stop();
	}

	private async spawnApi(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			throw new Error('Starting the sim API is denied in an untrusted workspace.');
		}
		const python = this.pythonPath;
		const env = {
			...process.env,
			PYTHONPATH: path.join(this.pythonRoot, 'src'),
			PYTHONUNBUFFERED: '1',
			CERTIQS_HOST: '127.0.0.1',
			CERTIQS_PORT: String(this.port),
			CERTIQS_CONFIG_ROOT: path.join(this.pythonRoot, 'config'),
			CERTIQS_DEFAULT_CONFIG: 'bbm92-minimal',
			CERTIQS_LOG_JSON: 'false',
		};
		const command = `${python} -m certiqs_sim.services.api`;
		this.output.appendLine(`$ ${command}`);
		this.output.appendLine(`PYTHONPATH=${env.PYTHONPATH}`);
		this.output.appendLine(`CERTIQS_CONFIG_ROOT=${env.CERTIQS_CONFIG_ROOT}`);
		this.log(`starting ${command} on 127.0.0.1:${this.port}`);
		this.processLog?.command(command);

		const child = spawn(python, ['-m', 'certiqs_sim.services.api'], {
			cwd: this.pythonRoot,
			env,
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

		const deadline = Date.now() + 15_000;
		while (Date.now() < deadline) {
			if (child.exitCode !== null) {
				throw new Error(`Sim API exited before it became ready (code ${child.exitCode}). See the certiqs Sim output channel. Install control-plane deps with: ${python} -m pip install -r ${path.join(this.pythonRoot, 'requirements-ide.txt')}`);
			}
			if (await this.client.health()) {
				this.output.appendLine('api ready');
				return;
			}
			await delay(300);
		}
		throw new Error(`Sim API did not become ready on ${this.client.origin}.`);
	}
}

export type EngineInfo = {
	installed: boolean;
	version?: string;
	pythonVersion: string;
	platform: string;
	machine: string;
};

function delay(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}

function redactIndex(text: string): string {
	return text.replace(/https:\/\/[^/\s]+@pypi\.netsquid\.org/gi, 'https://***@pypi.netsquid.org');
}
