/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { ChildProcess, spawn } from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import { EngineInfo, ProcessLogSink } from './pythonRuntime';
import { SimClient } from './simClient';

export const SIM_CONTAINER_NAME = 'certiqs-sim-api';
export const SIM_SERVICE_LABEL = 'certiqs.service=certiqs.sim';
export const DEFAULT_SIM_IMAGE = 'certiqs-sim:local';

export type DockerContainerInfo = {
	id: string;
	name: string;
	status: string;
	image: string;
};

export class DockerRuntime implements vscode.Disposable {
	private logsFollow: ChildProcess | undefined;
	private starting: Promise<void> | undefined;
	private processLog: ProcessLogSink | undefined;

	constructor(
		private readonly extensionUri: vscode.Uri,
		private readonly output: vscode.OutputChannel,
	) { }

	attachProcessLog(sink: ProcessLogSink): void {
		this.processLog = sink;
	}

	get port(): number {
		return vscode.workspace.getConfiguration('certiqs.sim').get<number>('port', 8011);
	}

	get imageTag(): string {
		const configured = vscode.workspace.getConfiguration('certiqs.sim').get<string>('dockerImage', '').trim();
		return configured || DEFAULT_SIM_IMAGE;
	}

	get usesLocalDockerfile(): boolean {
		return !vscode.workspace.getConfiguration('certiqs.sim').get<string>('dockerImage', '').trim();
	}

	get client(): SimClient {
		return new SimClient(this.port);
	}

	get pythonRoot(): string {
		return path.join(this.extensionUri.fsPath, 'python');
	}

	async available(): Promise<boolean> {
		const result = await this.exec(['version', '--format', '{{.Server.Version}}'], { ignoreFail: true });
		return result.code === 0 && Boolean(result.stdout.trim());
	}

	async inspect(): Promise<DockerContainerInfo | undefined> {
		const result = await this.exec([
			'inspect',
			'--format',
			'{{.Id}} {{.State.Status}} {{.Config.Image}} {{.Name}}',
			SIM_CONTAINER_NAME,
		], { ignoreFail: true });
		if (result.code !== 0) {
			return undefined;
		}
		const [id, status, image, name] = result.stdout.trim().split(/\s+/);
		if (!id || !status) {
			return undefined;
		}
		return { id, status, image, name: (name ?? SIM_CONTAINER_NAME).replace(/^\//, '') };
	}

	async ensureStarted(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			throw new Error('Starting the sim API is denied in an untrusted workspace.');
		}
		if (!await this.available()) {
			throw new Error('Docker is not available. Install Docker Desktop or the Docker engine, or switch Runtime mode to Local Python.');
		}
		const owned = await this.inspect();
		if (owned && isRunning(owned.status) && await this.client.health()) {
			this.followLogs();
			return;
		}
		if (!owned && await this.client.health()) {
			throw new Error(`Port ${this.port} is already in use by a process this extension does not own.`);
		}
		if (!this.starting) {
			this.starting = this.startContainer(owned).finally(() => {
				this.starting = undefined;
			});
		}
		await this.starting;
	}

	async stop(): Promise<void> {
		this.stopLogFollow();
		const owned = await this.inspect();
		if (!owned) {
			return;
		}
		this.output.appendLine(`$ docker stop ${SIM_CONTAINER_NAME}`);
		await this.exec(['stop', SIM_CONTAINER_NAME], { ignoreFail: true });
		this.output.appendLine(`$ docker rm ${SIM_CONTAINER_NAME}`);
		await this.exec(['rm', SIM_CONTAINER_NAME], { ignoreFail: true });
	}

	async rebuild(): Promise<void> {
		if (!await this.available()) {
			throw new Error('Docker is not available.');
		}
		if (this.usesLocalDockerfile) {
			await this.buildImage();
		} else {
			this.output.appendLine(`$ docker pull ${this.imageTag}`);
			this.output.show(true);
			await this.spawnLogged(['pull', this.imageTag]);
		}
		const owned = await this.inspect();
		if (owned && isRunning(owned.status)) {
			await this.stop();
			await this.ensureStarted();
		}
	}

	async dumpLogs(): Promise<void> {
		this.output.show(true);
		if (!await this.inspect()) {
			this.output.appendLine('no certiqs-sim-api container');
			return;
		}
		this.followLogs();
	}

	async hasEngine(): Promise<boolean> {
		return (await this.inspectEngine()).installed;
	}

	async inspectEngine(): Promise<EngineInfo> {
		const owned = await this.inspect();
		if (!owned || !isRunning(owned.status)) {
			return { installed: false, pythonVersion: 'container', platform: 'docker', machine: process.arch };
		}
		const python = await this.exec([
			'exec', SIM_CONTAINER_NAME, 'python', '-c',
			'import platform,sys; print(sys.version.split()[0]); print(sys.platform); print(platform.machine())',
		], { ignoreFail: true });
		const [pythonVersion, platformName, machine] = python.stdout.trim().split(/\r?\n/);
		const engine = await this.exec([
			'exec', SIM_CONTAINER_NAME, 'python', '-c', 'import netsquid; print(netsquid.__version__)',
		], { ignoreFail: true });
		return {
			installed: engine.code === 0 && Boolean(engine.stdout.trim()),
			version: engine.code === 0 ? engine.stdout.trim().split(/\r?\n/)[0] : undefined,
			pythonVersion: pythonVersion || 'unknown',
			platform: platformName || 'linux',
			machine: machine || process.arch,
		};
	}

	dispose(): void {
		this.stopLogFollow();
	}

	private async startContainer(existing: DockerContainerInfo | undefined): Promise<void> {
		await this.ensureImage();
		if (existing && !isRunning(existing.status)) {
			this.output.appendLine(`$ docker start ${SIM_CONTAINER_NAME}`);
			this.output.show(true);
			this.processLog?.command(`docker start ${SIM_CONTAINER_NAME}`);
			await this.spawnLogged(['start', SIM_CONTAINER_NAME]);
		} else if (!existing) {
			const args = [
				'run', '-d',
				'--name', SIM_CONTAINER_NAME,
				'--label', SIM_SERVICE_LABEL,
				'--label', 'certiqs.managed=true',
				'-p', `127.0.0.1:${this.port}:${this.port}`,
				'-e', 'CERTIQS_HOST=0.0.0.0',
				'-e', `CERTIQS_PORT=${this.port}`,
				'-e', 'CERTIQS_CONFIG_ROOT=/workspace-config',
				'-e', 'CERTIQS_DEFAULT_CONFIG=bbm92-minimal',
				'-e', 'CERTIQS_LOG_JSON=false',
				'-v', `${path.join(this.pythonRoot, 'config')}:/workspace-config:ro`,
				this.imageTag,
			];
			this.output.appendLine(`$ docker ${args.join(' ')}`);
			this.output.show(true);
			this.processLog?.command(`docker ${args.join(' ')}`);
			await this.spawnLogged(args);
		}
		this.followLogs();
		const deadline = Date.now() + 20_000;
		while (Date.now() < deadline) {
			const owned = await this.inspect();
			if (!owned) {
				throw new Error('Sim API container disappeared before it became ready. See the certiqs Sim output channel.');
			}
			if (!isRunning(owned.status)) {
				throw new Error(`Sim API container exited (${owned.status}). See the certiqs Sim output channel.`);
			}
			if (await this.client.health()) {
				this.output.appendLine('api ready');
				return;
			}
			await delay(300);
		}
		throw new Error(`Sim API did not become ready on ${this.client.origin}.`);
	}

	private async ensureImage(): Promise<void> {
		if (!this.usesLocalDockerfile) {
			const found = await this.exec(['image', 'inspect', this.imageTag], { ignoreFail: true });
			if (found.code === 0) {
				return;
			}
			this.output.appendLine(`$ docker pull ${this.imageTag}`);
			this.output.show(true);
			await this.spawnLogged(['pull', this.imageTag]);
			return;
		}
		const found = await this.exec(['image', 'inspect', DEFAULT_SIM_IMAGE], { ignoreFail: true });
		if (found.code === 0) {
			return;
		}
		await this.buildImage();
	}

	private async buildImage(): Promise<void> {
		const dockerfile = path.join(this.extensionUri.fsPath, 'docker', 'Dockerfile');
		const args = ['build', '-t', DEFAULT_SIM_IMAGE, '-f', dockerfile, this.extensionUri.fsPath];
		this.output.appendLine(`$ docker ${args.join(' ')}`);
		this.output.show(true);
		await this.spawnLogged(args, this.extensionUri.fsPath);
	}

	private followLogs(): void {
		if (this.logsFollow && this.logsFollow.exitCode === null) {
			return;
		}
		this.stopLogFollow();
		const child = spawn('docker', ['logs', '-f', '--tail', '80', SIM_CONTAINER_NAME], {
			stdio: ['ignore', 'pipe', 'pipe'],
		});
		this.logsFollow = child;
		child.stdout?.on('data', chunk => this.output.append(redactIndex(String(chunk))));
		child.stderr?.on('data', chunk => this.output.append(redactIndex(String(chunk))));
		child.on('exit', () => {
			if (this.logsFollow === child) {
				this.logsFollow = undefined;
			}
		});
	}

	private stopLogFollow(): void {
		const child = this.logsFollow;
		this.logsFollow = undefined;
		if (child && child.exitCode === null) {
			child.kill('SIGTERM');
		}
	}

	private exec(args: string[], options?: { ignoreFail?: boolean }): Promise<{ code: number; stdout: string; stderr: string }> {
		return new Promise((resolve, reject) => {
			const child = spawn('docker', args, { stdio: ['ignore', 'pipe', 'pipe'] });
			let stdout = '';
			let stderr = '';
			child.stdout?.on('data', chunk => {
				stdout += String(chunk);
			});
			child.stderr?.on('data', chunk => {
				stderr += String(chunk);
			});
			child.on('error', error => {
				if (options?.ignoreFail) {
					resolve({ code: 1, stdout, stderr: error.message });
					return;
				}
				reject(error);
			});
			child.on('exit', code => {
				const result = { code: code ?? 1, stdout, stderr };
				if (result.code !== 0 && !options?.ignoreFail) {
					reject(new Error(stderr.trim() || `docker ${args[0]} exited ${result.code}`));
					return;
				}
				resolve(result);
			});
		});
	}

	private spawnLogged(args: string[], cwd?: string): Promise<void> {
		return new Promise((resolve, reject) => {
			const child = spawn('docker', args, {
				cwd,
				stdio: ['ignore', 'pipe', 'pipe'],
			});
			child.stdout?.on('data', chunk => this.output.append(redactIndex(String(chunk))));
			child.stderr?.on('data', chunk => this.output.append(redactIndex(String(chunk))));
			child.on('error', reject);
			child.on('exit', code => {
				if (code === 0) {
					resolve();
					return;
				}
				reject(new Error(`docker ${args[0]} exited ${code}. See the certiqs Sim output channel.`));
			});
		});
	}
}

export function isRunning(status: string | undefined): boolean {
	return status === 'running';
}

function delay(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}

function redactIndex(text: string): string {
	return text.replace(/https:\/\/[^/\s]+@pypi\.netsquid\.org/gi, 'https://***@pypi.netsquid.org');
}
