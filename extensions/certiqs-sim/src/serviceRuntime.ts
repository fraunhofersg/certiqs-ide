/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { DockerRuntime, isRunning, SIM_CONTAINER_NAME } from './dockerRuntime';
import { EngineInfo, ProcessLogSink, PythonRuntime } from './pythonRuntime';
import { RuntimeMode, RuntimeSnapshot, RuntimeState } from './runtime/types';
import { SimClient } from './simClient';

export class ServiceRuntime implements vscode.Disposable {
	readonly local: PythonRuntime;
	readonly docker: DockerRuntime;
	private readonly output: vscode.OutputChannel;
	private lastError: string | undefined;
	private starting = false;

	constructor(extensionUri: vscode.Uri) {
		this.output = vscode.window.createOutputChannel('certiqs Sim');
		this.local = new PythonRuntime(extensionUri, this.output);
		this.docker = new DockerRuntime(extensionUri, this.output);
	}

	get mode(): RuntimeMode {
		const value = vscode.workspace.getConfiguration('certiqs.sim').get<string>('runtimeMode', 'local');
		return value === 'docker' ? 'docker' : 'local';
	}

	get port(): number {
		return this.mode === 'docker' ? this.docker.port : this.local.port;
	}

	get pythonPath(): string {
		return this.local.pythonPath;
	}

	get processOutput(): vscode.OutputChannel {
		return this.output;
	}

	get client(): SimClient {
		return new SimClient(this.port);
	}

	attachProcessLog(sink: ProcessLogSink): void {
		this.local.attachProcessLog(sink);
		this.docker.attachProcessLog(sink);
	}

	async ensureStarted(): Promise<void> {
		this.starting = true;
		this.lastError = undefined;
		try {
			if (this.mode === 'docker') {
				await this.docker.ensureStarted();
			} else {
				await this.local.ensureStarted();
			}
		} catch (error) {
			this.lastError = (error as Error).message;
			throw error;
		} finally {
			this.starting = false;
		}
	}

	async stop(): Promise<void> {
		this.lastError = undefined;
		if (this.mode === 'docker') {
			await this.docker.stop();
			return;
		}
		await this.local.stop();
	}

	async restart(): Promise<void> {
		await this.stop();
		await this.ensureStarted();
	}

	async rebuild(): Promise<void> {
		if (this.mode !== 'docker') {
			throw new Error('Rebuild is only available in Docker runtime mode.');
		}
		await this.docker.rebuild();
	}

	async snapshot(): Promise<RuntimeSnapshot> {
		const mode = this.mode;
		const dockerAvailable = await this.docker.available();
		const container = await this.docker.inspect();
		let state: RuntimeState = this.starting ? 'starting' : 'stopped';
		let reason = this.lastError;
		try {
			const health = await this.client.health();
			const owned = mode === 'docker'
				? Boolean(container && isRunning(container.status) && health)
				: this.local.hasTrackedProcess() && health;
			if (owned) {
				state = 'ready';
				reason = undefined;
			} else if (health) {
				state = 'failed';
				reason = `Port ${this.port} is in use by a process this extension does not own.`;
			} else if (mode === 'docker' && !dockerAvailable) {
				state = 'failed';
				reason = 'Docker is not available.';
			} else if (this.lastError) {
				state = 'failed';
			}
		} catch (error) {
			state = 'failed';
			reason = (error as Error).message;
		}
		return {
			id: 'certiqs-sim',
			title: 'Simulation API',
			mode,
			state,
			endpoint: `http://127.0.0.1:${this.port}`,
			reason,
			docker: {
				available: dockerAvailable,
				image: this.docker.imageTag,
				containerName: SIM_CONTAINER_NAME,
				containerId: container?.id,
				status: container?.status,
			},
		};
	}

	async hasEngine(): Promise<boolean> {
		return (await this.inspectEngine()).installed;
	}

	async inspectEngine(): Promise<EngineInfo> {
		if (this.mode === 'docker') {
			return this.docker.inspectEngine();
		}
		return this.local.inspectEngine();
	}

	async latestNetsquidVersion(extraIndexUrl: string): Promise<string | undefined> {
		return this.local.latestNetsquidVersion(extraIndexUrl);
	}

	async installPackage(spec: string, extraIndexUrl: string): Promise<void> {
		if (this.mode === 'docker') {
			throw new Error('Install NetSquid on the host only in Local Python mode. Docker images do not install the engine via host pip in this slice.');
		}
		await this.local.installPackage(spec, extraIndexUrl);
	}

	appendLog(line: string): void {
		this.local.appendLog(line);
	}

	showOutput(): void {
		if (this.mode === 'docker') {
			void this.docker.dumpLogs();
			return;
		}
		this.local.showOutput();
	}

	dispose(): void {
		void this.stop();
		this.docker.dispose();
		this.local.dispose();
		this.output.dispose();
	}
}
