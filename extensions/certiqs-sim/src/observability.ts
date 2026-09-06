/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import type { DataPoint, MetricCatalogEntry, RunStatus } from './apiTypes';

export type ProblemItem = {
	message: string;
	severity: 'error' | 'warning' | 'info';
	source: string;
};

export class SimObservability implements vscode.Disposable {
	readonly process: vscode.OutputChannel;
	readonly monitor: vscode.OutputChannel;
	readonly forensics: vscode.OutputChannel;
	readonly debug: vscode.OutputChannel;
	private readonly diagnostics: vscode.DiagnosticCollection;
	private lastQberZone = 'ok';
	private lastAlarm = 0;

	constructor(process?: vscode.OutputChannel) {
		this.process = process ?? vscode.window.createOutputChannel('certiqs Sim');
		this.monitor = vscode.window.createOutputChannel('certiqs Sim — Monitor');
		this.forensics = vscode.window.createOutputChannel('certiqs Sim — Forensics');
		this.debug = vscode.window.createOutputChannel('certiqs Sim — Debug');
		this.diagnostics = vscode.languages.createDiagnosticCollection('certiqs-sim');
	}

	appendProcess(text: string): void {
		this.process.append(text.endsWith('\n') ? text : `${text}\n`);
	}

	appendMonitor(line: string): void {
		this.monitor.appendLine(line);
	}

	appendForensics(line: string): void {
		this.forensics.appendLine(line);
	}

	appendDebug(line: string): void {
		this.debug.appendLine(line);
	}

	showProcess(): void {
		this.process.show(true);
	}

	showMonitor(): void {
		this.monitor.show(true);
	}

	showForensics(): void {
		this.forensics.show(true);
	}

	showDebug(): void {
		this.debug.show(true);
	}

	setProblems(items: ProblemItem[]): void {
		const uri = vscode.Uri.parse('certiqs-sim:/run');
		this.diagnostics.set(uri, items.map(item => {
			const diagnostic = new vscode.Diagnostic(
				new vscode.Range(0, 0, 0, 80),
				item.message,
				item.severity === 'error'
					? vscode.DiagnosticSeverity.Error
					: item.severity === 'warning'
						? vscode.DiagnosticSeverity.Warning
						: vscode.DiagnosticSeverity.Information,
			);
			diagnostic.source = item.source;
			return diagnostic;
		}));
	}

	clearProblems(): void {
		this.diagnostics.clear();
	}

	observeStatus(status: RunStatus): void {
		this.appendDebug(`status=${status.status} run=${status.run_id ?? '—'} epoch=${status.epoch ?? 0} config=${status.config_name ?? '—'}${status.error ? ` error=${status.error}` : ''}`);
		if (status.error) {
			this.setProblems([{ message: status.error, severity: 'error', source: 'certiqs-sim' }]);
		}
	}

	observePoint(point: DataPoint, catalog: MetricCatalogEntry[]): void {
		const qber = numberOf(point.metrics.qber);
		const alarm = numberOf(point.metrics.selftest_alarm);
		const qberZone = zoneFor(qber, catalog.find(item => item.key === 'qber'));
		if (qberZone !== this.lastQberZone) {
			const line = `epoch ${point.epoch}: QBER ${qber ?? '—'} → ${qberZone}`;
			this.appendMonitor(line);
			if (qberZone === 'danger' || qberZone === 'warning') {
				this.setProblems([{ message: line, severity: qberZone === 'danger' ? 'error' : 'warning', source: 'certiqs-sim.monitor' }]);
			} else if (this.lastQberZone !== 'ok') {
				this.clearProblems();
			}
			this.lastQberZone = qberZone;
		}
		if (alarm >= 1 && this.lastAlarm < 1) {
			const line = `epoch ${point.epoch}: self-test alarm`;
			this.appendForensics(line);
			this.setProblems([{ message: line, severity: 'error', source: 'certiqs-sim.forensics' }]);
		}
		this.lastAlarm = alarm;
	}

	resetRun(): void {
		this.lastQberZone = 'ok';
		this.lastAlarm = 0;
		this.clearProblems();
		this.appendDebug('run idle');
	}

	dispose(): void {
		this.monitor.dispose();
		this.forensics.dispose();
		this.debug.dispose();
		this.diagnostics.dispose();
	}
}

function numberOf(value: number | null | undefined): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function zoneFor(value: number | null, metric?: MetricCatalogEntry): string {
	if (value == null) {
		return 'ok';
	}
	const abort = metric?.technical_range?.abort_threshold;
	const warn = metric?.technical_range?.warning_threshold;
	if (typeof abort === 'number' && value >= abort) {
		return 'danger';
	}
	if (typeof warn === 'number' && value >= warn) {
		return 'warning';
	}
	if (!metric && value >= 0.11) {
		return 'danger';
	}
	if (!metric && value >= 0.05) {
		return 'warning';
	}
	return 'ok';
}
