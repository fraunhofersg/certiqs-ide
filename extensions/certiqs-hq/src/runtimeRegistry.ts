/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import {
	CertiqsRuntimeContribution,
	RuntimeCommand,
	RuntimeSnapshot,
} from './runtimeContract';

export async function loadRuntimeCatalog(): Promise<RuntimeSnapshot[]> {
	const snapshots: RuntimeSnapshot[] = [];
	for (const extension of vscode.extensions.all) {
		const raw = extension.packageJSON?.contributes?.certiqsRuntime as CertiqsRuntimeContribution | undefined;
		if (!raw?.command || !raw.id) {
			continue;
		}
		try {
			await extension.activate();
			const snapshot = await vscode.commands.executeCommand(raw.command, { type: 'status' } satisfies RuntimeCommand);
			if (isSnapshot(snapshot)) {
				snapshots.push(snapshot);
			}
		} catch (error) {
			console.warn(`certiqs runtime: skipped ${raw.command}`, error);
			snapshots.push({
				id: raw.id,
				title: raw.id,
				mode: 'local',
				state: 'failed',
				reason: (error as Error).message,
			});
		}
	}
	return snapshots;
}

export async function runRuntimeCommand(sourceId: string, command: RuntimeCommand): Promise<RuntimeSnapshot | undefined> {
	const target = findContribution(sourceId);
	if (!target) {
		throw new Error(`No runtime contributor registered as ${sourceId}.`);
	}
	const snapshot = await vscode.commands.executeCommand(target.command, command);
	return isSnapshot(snapshot) ? snapshot : undefined;
}

function findContribution(sourceId: string): CertiqsRuntimeContribution | undefined {
	for (const extension of vscode.extensions.all) {
		const raw = extension.packageJSON?.contributes?.certiqsRuntime as CertiqsRuntimeContribution | undefined;
		if (raw?.id === sourceId && raw.command) {
			return raw;
		}
	}
	return undefined;
}

function isSnapshot(value: unknown): value is RuntimeSnapshot {
	return Boolean(
		value
		&& typeof value === 'object'
		&& 'id' in value
		&& 'title' in value
		&& 'mode' in value
		&& 'state' in value,
	);
}
