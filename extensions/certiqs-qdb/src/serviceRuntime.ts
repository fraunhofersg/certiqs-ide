/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import {
	AI_GATEWAY_KEY,
	ANTHROPIC_KEY,
	DATABASE_URL_KEY,
	INTERNAL_AUTH_SECRET_KEY,
	NEO4J_PASSWORD_KEY,
	QdbEnv,
	VOYAGE_KEY,
} from './credentials';
import { DockerRuntime, QDB_CONTAINER_NAME } from './dockerRuntime';
import { generateInternalAuthSecret } from './internalAuth';
import { PythonRuntime } from './pythonRuntime';
import { RuntimeMode, RuntimeSnapshot, RuntimeState } from './runtime/types';

export class ServiceRuntime implements vscode.Disposable {
	readonly local: PythonRuntime;
	readonly docker: DockerRuntime;
	private readonly output: vscode.OutputChannel;
	private lastError: string | undefined;
	private starting = false;

	constructor(
		private readonly context: vscode.ExtensionContext,
	) {
		this.output = vscode.window.createOutputChannel('certiqs QDB');
		const loadEnv = () => this.loadEnv();
		this.local = new PythonRuntime(context.extensionUri, this.output, loadEnv);
		this.docker = new DockerRuntime(context.extensionUri, this.output, loadEnv);
	}

	get mode(): RuntimeMode {
		const value = vscode.workspace.getConfiguration('certiqs.qdb').get<string>('runtimeMode', 'local');
		return value === 'docker' ? 'docker' : 'local';
	}

	get port(): number {
		return this.mode === 'docker' ? this.docker.port : this.local.port;
	}

	get pythonPath(): string {
		return this.local.pythonPath;
	}

	get origin(): string {
		return `http://127.0.0.1:${this.port}`;
	}

	get processOutput(): vscode.OutputChannel {
		return this.output;
	}

	async loadEnv(): Promise<QdbEnv> {
		const cfg = vscode.workspace.getConfiguration('certiqs.qdb');
		let secret = await this.context.secrets.get(INTERNAL_AUTH_SECRET_KEY) ?? '';
		if (!secret) {
			secret = generateInternalAuthSecret();
			await this.context.secrets.store(INTERNAL_AUTH_SECRET_KEY, secret);
		}
		return {
			databaseUrl: await this.context.secrets.get(DATABASE_URL_KEY) ?? '',
			internalAuthSecret: secret,
			internalAuthTtlSeconds: cfg.get<number>('internalAuthTtlSeconds', 60),
			neonHttpFallback: cfg.get<boolean>('neonHttpFallback', false),
			neo4jUri: cfg.get<string>('neo4jUri', ''),
			neo4jUsername: cfg.get<string>('neo4jUsername', ''),
			neo4jPassword: await this.context.secrets.get(NEO4J_PASSWORD_KEY) ?? '',
			anthropicApiKey: await this.context.secrets.get(ANTHROPIC_KEY) ?? '',
			voyageApiKey: await this.context.secrets.get(VOYAGE_KEY) ?? '',
			aiGatewayApiKey: await this.context.secrets.get(AI_GATEWAY_KEY) ?? '',
			aiGatewayBaseUrl: cfg.get<string>('aiGatewayBaseUrl', ''),
		};
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
		await this.docker.rebuild();
	}

	showOutput(): void {
		this.output.show(true);
	}

	async health(): Promise<boolean> {
		return this.mode === 'docker' ? this.docker.health() : this.local.health();
	}

	async snapshot(): Promise<RuntimeSnapshot> {
		const docker = await this.docker.inspect();
		const ready = await this.health();
		let state: RuntimeState = 'stopped';
		if (this.starting) {
			state = 'starting';
		} else if (this.lastError) {
			state = 'failed';
		} else if (ready) {
			state = 'ready';
		}
		return {
			id: 'certiqs-qdb',
			title: 'QDB',
			mode: this.mode,
			state,
			endpoint: ready ? this.origin : undefined,
			reason: this.lastError,
			docker: {
				available: docker.available,
				image: this.docker.image,
				containerName: QDB_CONTAINER_NAME,
				containerId: docker.containerId,
				status: docker.status,
			},
		};
	}

	dispose(): void {
		this.output.dispose();
		this.local.dispose();
		this.docker.dispose();
	}
}
