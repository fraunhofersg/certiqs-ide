/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { BootstrapSnapshot, DataPoint, MetricCatalogEntry, StreamMessage } from './apiTypes';
import { SimObservability } from './observability';
import { PROCESS_LABELS, HostToWebview, RunLifecycle, RpcMethod, SimState, WebviewToHost } from './protocol';
import { ServiceRuntime } from './serviceRuntime';
import { SimTerminals } from './simTerminals';

export type SimMessenger = {
	post(message: HostToWebview): Thenable<boolean> | undefined;
};

export class SimSession implements vscode.Disposable {
	readonly logs: SimObservability;
	readonly terminals: SimTerminals;
	configName = 'bbm92-minimal';
	shotsPerWindow = 100_000;
	lifecycle: RunLifecycle = 'idle';
	apiHint: SimState['api'] | undefined;
	private readonly views = new Set<SimMessenger>();
	private poll: ReturnType<typeof setInterval> | undefined;
	private closeStream: (() => void) | undefined;
	private streamBuffer: StreamMessage[] = [];
	private flushTimer: ReturnType<typeof setTimeout> | undefined;
	private catalog: MetricCatalogEntry[] = [];
	private points: DataPoint[] = [];
	private iconBase = '';

	constructor(private readonly runtime: ServiceRuntime) {
		this.logs = new SimObservability(runtime.processOutput);
		this.terminals = new SimTerminals(() => this.runtime.client);
		this.runtime.attachProcessLog({
			command: command => this.terminals.revealApi(command),
			line: line => this.terminals.appendApi(line),
		});
	}

	setIconBase(value: string): void {
		this.iconBase = value;
	}

	attach(view: SimMessenger): vscode.Disposable {
		this.views.add(view);
		return new vscode.Disposable(() => this.views.delete(view));
	}

	async handle(message: WebviewToHost): Promise<void> {
		switch (message.type) {
			case 'ready':
			case 'refresh':
				if (vscode.workspace.getConfiguration('certiqs.sim').get('autoStartApi', true)) {
					await this.startApi();
				} else {
					await this.broadcastState();
				}
				return;
			case 'startApi':
				await this.startApi();
				return;
			case 'stopApi':
				this.stopStream();
				await this.runtime.stop();
				this.stopPoll();
				await this.broadcastState();
				return;
			case 'setConfig':
				this.configName = message.configName;
				await this.broadcastState();
				return;
			case 'setShots':
				this.shotsPerWindow = Math.max(1000, message.shotsPerWindow);
				await this.broadcastState();
				return;
			case 'startRun':
				await this.startRun();
				return;
			case 'stopRun':
				await this.stopRun();
				return;
			case 'showLog':
				this.logs.showProcess();
				return;
			case 'showMonitor':
				this.logs.showMonitor();
				return;
			case 'showForensics':
				this.logs.showForensics();
				return;
			case 'showDebug':
				this.logs.showDebug();
				return;
			case 'showPrompt':
				this.terminals.revealPrompt();
				return;
			case 'openWelcome':
			case 'openOverview':
				await vscode.commands.executeCommand('certiqs.sim.openWelcome');
				return;
			case 'openDashboard':
				await vscode.commands.executeCommand('certiqs.sim.openDashboard');
				return;
			case 'openSystem':
				await vscode.commands.executeCommand('certiqs.sim.openSystem');
				return;
			case 'focusRunControl':
				await vscode.commands.executeCommand('certiqs.sim.panel.focus');
				return;
			case 'rpc':
				await this.rpc(message.id, message.method, message.params ?? {});
				return;
		}
	}

	async startApi(): Promise<void> {
		this.apiHint = 'starting';
		await this.broadcastState();
		try {
			await this.runtime.ensureStarted();
			const configs = await this.runtime.client.configs();
			if (configs.names.length && !configs.names.includes(this.configName)) {
				this.configName = configs.defaultConfig || configs.names[0];
			}
			this.apiHint = undefined;
			this.logs.appendDebug(`API ready on :${this.runtime.port}`);
		} catch (error) {
			this.apiHint = 'error';
			void vscode.window.showErrorMessage(`certiqs sim: ${(error as Error).message}`);
		}
		await this.broadcastState();
		this.startPoll();
	}

	async startRun(): Promise<void> {
		if (!vscode.workspace.isTrusted) {
			void vscode.window.showErrorMessage('Starting a simulation is denied in an untrusted workspace.');
			return;
		}
		this.lifecycle = 'starting';
		await this.broadcastState();
		try {
			await this.runtime.ensureStarted();
			const status = await this.runtime.client.startRun({
				configName: this.configName,
				shotsPerWindow: this.shotsPerWindow,
			});
			this.lifecycle = 'idle';
			if (status.config_name) {
				this.configName = status.config_name;
			}
			if (status.shots_per_window) {
				this.shotsPerWindow = status.shots_per_window;
			}
			this.logs.observeStatus(status);
			this.terminals.setRunId(status.run_id ?? undefined);
			if (status.run_id) {
				this.attachStream(status.run_id);
			}
		} catch (error) {
			this.lifecycle = 'idle';
			void vscode.window.showErrorMessage(`certiqs sim: ${(error as Error).message}`);
		}
		await this.broadcastState();
		this.startPoll();
	}

	async stopRun(): Promise<void> {
		this.lifecycle = 'stopping';
		await this.broadcastState();
		try {
			const status = await this.runtime.client.status();
			if (status.run_id) {
				await this.runtime.client.stopRun(status.run_id);
				await this.runtime.client.waitUntilStopped(status.run_id);
			}
		} catch (error) {
			void vscode.window.showErrorMessage(`certiqs sim: ${(error as Error).message}`);
		} finally {
			this.lifecycle = 'idle';
			this.stopStream();
			this.terminals.setRunId(undefined);
			this.logs.resetRun();
		}
		await this.broadcastState();
	}

	async readState(): Promise<SimState> {
		const client = this.runtime.client;
		let api: SimState['api'] = this.apiHint === 'starting' ? 'starting' : 'stopped';
		let apiError: string | undefined;
		let configs: string[] = [];
		let status = undefined;
		try {
			if (await client.health()) {
				api = 'ready';
				this.apiHint = undefined;
				const listed = await client.configs();
				configs = listed.names;
				status = await client.status();
				if (status.run_id && (status.status === 'running' || status.status === 'initialized')) {
					this.terminals.setRunId(status.run_id);
					if (!this.closeStream) {
						this.attachStream(status.run_id);
					}
				}
				if (!this.configName && (listed.defaultConfig || listed.names[0])) {
					this.configName = listed.defaultConfig || listed.names[0];
				}
			}
		} catch (error) {
			api = 'error';
			this.apiHint = 'error';
			apiError = (error as Error).message;
		}
		return {
			api,
			apiError,
			pythonPath: this.runtime.pythonPath,
			port: this.runtime.port,
			configs,
			configName: this.configName,
			shotsPerWindow: this.shotsPerWindow,
			lifecycle: this.lifecycle,
			status,
			labels: PROCESS_LABELS,
			notice: 'This panel talks to a local certiqsSim control plane. Results are simulated and are not a measurement.',
			iconBase: this.iconBase,
		};
	}

	async bootstrap(): Promise<BootstrapSnapshot> {
		const client = this.runtime.client;
		const listed = await client.getConfigs().catch(() => ({ configs: [], default_config: '', config_root: '' }));
		const status = await client.status().catch(() => null);
		let points: DataPoint[] = [];
		if (status?.run_id && (status.status === 'running' || status.status === 'stopping' || status.status === 'initialized')) {
			points = await client.getHistory(status.run_id).catch(() => []);
			this.points = points;
		}
		const catalog = await client.getMetricsCatalog().catch(() => []);
		this.catalog = catalog;
		return {
			meta: await client.getMeta().catch(() => null),
			catalog,
			configs: listed.configs ?? [],
			configName: this.configName,
			status,
			points,
			iconBase: this.iconBase,
		};
	}

	broadcast(message: HostToWebview): void {
		for (const view of this.views) {
			void view.post(message);
		}
	}

	async broadcastState(): Promise<void> {
		this.broadcast({ type: 'state', payload: await this.readState() });
	}

	dispose(): void {
		this.stopPoll();
		this.stopStream();
		this.logs.dispose();
		this.terminals.dispose();
	}

	private async rpc(id: string, method: RpcMethod, params: Record<string, unknown>): Promise<void> {
		try {
			const result = await this.invoke(method, params);
			this.broadcast({ type: 'rpcResult', id, result });
		} catch (error) {
			this.broadcast({ type: 'rpcError', id, error: (error as Error).message });
		}
	}

	private async invoke(method: RpcMethod, params: Record<string, unknown>): Promise<unknown> {
		const client = this.runtime.client;
		const config = typeof params.config === 'string' ? params.config : this.configName;
		const runId = typeof params.runId === 'string' ? params.runId : undefined;
		switch (method) {
			case 'getMeta':
				return client.getMeta();
			case 'getConfigs':
				return client.getConfigs();
			case 'getMetricsCatalog':
				return client.getMetricsCatalog();
			case 'getForensicsConfig':
				return client.getForensicsConfig(config);
			case 'getOptimizationConfig':
				return client.getOptimizationConfig(config);
			case 'getStatus':
				return client.status();
			case 'getHistory':
				if (!runId) {
					return [];
				}
				return client.getHistory(runId);
			case 'setParams':
				if (!runId) {
					throw new Error('No active run for setParams.');
				}
				return client.setParams(runId, (params.overrides ?? {}) as Record<string, number>);
			case 'getConfigFiles':
				return client.getConfigFiles(config);
			case 'getComponentInventory':
				return client.getComponentInventory(config);
			case 'getComponentTaxonomy':
				return client.getComponentTaxonomy(config);
			case 'getComponentTopology':
				return client.getComponentTopology(config);
			case 'getSimTerminalExamples':
				if (!runId) {
					throw new Error('No active run.');
				}
				return client.getSimTerminalExamples(runId);
			case 'postSimTerminalPrompt':
				if (!runId) {
					throw new Error('No active run.');
				}
				this.terminals.revealPrompt();
				return client.postSimTerminalPrompt(runId, String(params.prompt ?? ''));
			case 'getBootstrap':
				return this.bootstrap();
		}
	}

	private attachStream(runId: string): void {
		this.stopStream();
		this.closeStream = this.runtime.client.openStream(runId, frame => {
			this.ingest(frame);
			this.streamBuffer.push(frame);
			if (!this.flushTimer) {
				this.flushTimer = setTimeout(() => {
					this.flushTimer = undefined;
					const frames = this.streamBuffer;
					this.streamBuffer = [];
					if (frames.length) {
						this.broadcast({ type: 'stream', frames });
					}
				}, 200);
			}
		});
	}

	private ingest(frame: StreamMessage): void {
		if (frame.type === 'catalog' && Array.isArray(frame.data)) {
			this.catalog = frame.data as MetricCatalogEntry[];
		}
		if (frame.type === 'status' && frame.data && typeof frame.data === 'object') {
			this.logs.observeStatus(frame.data as import('./apiTypes').RunStatus);
		}
		if (frame.type === 'history' && Array.isArray(frame.data)) {
			this.points = frame.data as DataPoint[];
		}
		if (frame.type === 'datapoint' && frame.data && typeof frame.data === 'object') {
			const point = frame.data as DataPoint;
			this.points.push(point);
			if (this.points.length > 5000) {
				this.points = this.points.slice(-5000);
			}
			this.logs.observePoint(point, this.catalog);
		}
	}

	private startPoll(): void {
		this.stopPoll();
		this.poll = setInterval(() => {
			void this.broadcastState();
		}, 1000);
	}

	private stopPoll(): void {
		if (this.poll) {
			clearInterval(this.poll);
			this.poll = undefined;
		}
	}

	private stopStream(): void {
		this.closeStream?.();
		this.closeStream = undefined;
		if (this.flushTimer) {
			clearTimeout(this.flushTimer);
			this.flushTimer = undefined;
		}
		this.streamBuffer = [];
	}
}
