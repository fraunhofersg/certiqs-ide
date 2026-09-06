/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import type {
	ComponentInventoryResponse,
	ConfigFilesResponse,
	ConfigsResponse,
	DataPoint,
	MetaResponse,
	MetricCatalogEntry,
	RunStatus,
	SimTerminalPromptResponse,
	StreamMessage,
	TaxonomyResponse,
	TopologyResponse,
} from './apiTypes';

export class SimClient {
	constructor(private readonly port: number) { }

	get origin(): string {
		return `http://127.0.0.1:${this.port}`;
	}

	get wsOrigin(): string {
		return `ws://127.0.0.1:${this.port}`;
	}

	async health(): Promise<boolean> {
		try {
			const res = await fetch(`${this.origin}/healthz`);
			return res.ok;
		} catch {
			return false;
		}
	}

	async configs(): Promise<{ names: string[]; defaultConfig: string }> {
		const body = await this.get<ConfigsResponse>('/api/v1/configs');
		return {
			names: (body.configs ?? []).map(item => item.name),
			defaultConfig: body.default_config ?? '',
		};
	}

	async getConfigs(): Promise<ConfigsResponse> {
		return this.get('/api/v1/configs');
	}

	async getMeta(): Promise<MetaResponse> {
		return this.get('/api/v1/meta');
	}

	async getMetricsCatalog(): Promise<MetricCatalogEntry[]> {
		const body = await this.get<{ metrics: MetricCatalogEntry[] }>('/api/v1/metrics/catalog');
		return body.metrics ?? [];
	}

	async getForensicsConfig(config?: string): Promise<Record<string, unknown>> {
		return this.get(`/api/v1/forensics/config${query({ config })}`);
	}

	async getOptimizationConfig(config?: string): Promise<Record<string, unknown>> {
		return this.get(`/api/v1/optimization/config${query({ config })}`);
	}

	async status(): Promise<RunStatus> {
		return this.get('/api/v1/status');
	}

	async getHistory(runId: string, since = -1): Promise<DataPoint[]> {
		const body = await this.get<{ points: DataPoint[] }>(`/api/v1/runs/${encodeURIComponent(runId)}/history?since=${since}`);
		return body.points ?? [];
	}

	async startRun(input: { configName: string; shotsPerWindow: number }): Promise<RunStatus> {
		return this.post('/api/v1/runs', {
			config_name: input.configName,
			protocol: 'bbm92',
			shots_per_window: input.shotsPerWindow,
			overrides: {},
			attack: { enabled: false },
			selftest: { enabled: false },
		});
	}

	async waitUntilStopped(runId: string, timeoutMs = 30_000): Promise<RunStatus> {
		const deadline = Date.now() + timeoutMs;
		let status = await this.status();
		while (Date.now() < deadline) {
			if (!status.run_id || status.run_id !== runId || status.status === 'idle' || status.status === 'stopped') {
				return status;
			}
			if (status.status !== 'running' && status.status !== 'stopping') {
				return status;
			}
			await delay(400);
			status = await this.status();
		}
		return status;
	}

	async stopRun(runId: string): Promise<RunStatus> {
		return this.post(`/api/v1/runs/${encodeURIComponent(runId)}/stop`);
	}

	async setParams(runId: string, overrides: Record<string, number>): Promise<unknown> {
		return this.post(`/api/v1/runs/${encodeURIComponent(runId)}/params`, { overrides });
	}

	async getConfigFiles(config?: string): Promise<ConfigFilesResponse> {
		return this.get(`/api/v1/components/files${query({ config })}`);
	}

	async getComponentInventory(config?: string): Promise<ComponentInventoryResponse> {
		return this.get(`/api/v1/components/inventory${query({ config })}`);
	}

	async getComponentTaxonomy(config?: string): Promise<TaxonomyResponse> {
		return this.get(`/api/v1/components/taxonomy${query({ config })}`);
	}

	async getComponentTopology(config?: string): Promise<TopologyResponse> {
		return this.get(`/api/v1/components/topology${query({ config })}`);
	}

	async getSimTerminalExamples(runId: string): Promise<unknown> {
		return this.get(`/api/v1/runs/${encodeURIComponent(runId)}/terminal/examples`);
	}

	async postSimTerminalPrompt(runId: string, prompt: string): Promise<SimTerminalPromptResponse> {
		return this.post(`/api/v1/runs/${encodeURIComponent(runId)}/terminal`, { prompt });
	}

	openStream(runId: string, onFrame: (frame: StreamMessage) => void): () => void {
		const url = `${this.wsOrigin}/api/v1/runs/${encodeURIComponent(runId)}/stream`;
		let since = -1;
		let poll: ReturnType<typeof setInterval> | undefined;
		const startPoll = () => {
			if (poll) {
				return;
			}
			poll = setInterval(() => {
				void this.getHistory(runId, since).then(points => {
					for (const point of points) {
						since = Math.max(since, point.epoch);
						onFrame({ type: 'datapoint', data: point });
					}
				}).catch(() => { });
			}, 500);
		};
		try {
			const socket = new WebSocket(url);
			socket.addEventListener('message', event => {
				try {
					const frame = JSON.parse(String(event.data)) as StreamMessage;
					onFrame(frame);
				} catch {
					// ignore malformed frames
				}
			});
			socket.addEventListener('error', () => startPoll());
			return () => {
				if (poll) {
					clearInterval(poll);
				}
				try {
					socket.close();
				} catch {
					// already closed
				}
			};
		} catch {
			startPoll();
			return () => {
				if (poll) {
					clearInterval(poll);
				}
			};
		}
	}

	private async get<T>(path: string): Promise<T> {
		const res = await fetch(`${this.origin}${path}`);
		const body = await res.json() as unknown;
		if (!res.ok) {
			throw new Error(detailFromBody(body, `${path} failed: ${res.status}`));
		}
		return body as T;
	}

	private async post<T>(path: string, payload?: unknown): Promise<T> {
		const res = await fetch(`${this.origin}${path}`, {
			method: 'POST',
			headers: payload ? { 'Content-Type': 'application/json' } : undefined,
			body: payload ? JSON.stringify(payload) : undefined,
		});
		const body = await res.json() as unknown;
		if (!res.ok) {
			throw new Error(detailFromBody(body, `${path} failed: ${res.status}`));
		}
		return body as T;
	}
}

function query(params: Record<string, string | undefined>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value) {
			search.set(key, value);
		}
	}
	const text = search.toString();
	return text ? `?${text}` : '';
}

function detailFromBody(body: unknown, fallback: string): string {
	if (!body || typeof body !== 'object' || !('detail' in body)) {
		return fallback;
	}
	const detail = (body as { detail: unknown }).detail;
	if (typeof detail === 'string' && detail.trim()) {
		return detail;
	}
	if (Array.isArray(detail)) {
		const parts = detail
			.map(item => typeof item === 'string' ? item : (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : ''))
			.filter(Boolean);
		if (parts.length) {
			return parts.join('; ');
		}
	}
	return fallback;
}

function delay(ms: number): Promise<void> {
	return new Promise(resolve => setTimeout(resolve, ms));
}

