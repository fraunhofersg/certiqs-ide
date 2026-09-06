/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { applyHqSettings } from './hqSettings';
import {
	CertiqsSettingsContribution,
	SettingsCatalog,
	SettingsCommand,
	SettingsManifest,
	SettingsSnapshot,
	SettingsSourceState,
} from './settingsContract';

export async function loadSettingsCatalog(local: SettingsSourceState): Promise<SettingsCatalog> {
	const sources: SettingsSourceState[] = [local];
	for (const extension of vscode.extensions.all) {
		const raw = extension.packageJSON?.contributes?.certiqsSettings as CertiqsSettingsContribution | undefined;
		if (!raw?.command || raw.id === local.id) {
			continue;
		}
		try {
			await extension.activate();
			const described = await vscode.commands.executeCommand(raw.command, { type: 'describe' } satisfies SettingsCommand);
			const snapshot = await vscode.commands.executeCommand(raw.command, { type: 'get' } satisfies SettingsCommand);
			if (isManifest(described) && isSnapshot(snapshot)) {
				sources.push({ ...described, ...snapshot });
			}
		} catch (error) {
			console.warn(`certiqs settings: skipped ${raw.command}`, error);
		}
	}
	sources.sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
	return { sources };
}

export async function runSettingsCommand(sourceId: string, command: SettingsCommand, local: SettingsSourceState, extensionUri: vscode.Uri): Promise<void> {
	if (sourceId === local.id) {
		if (command.type === 'set') {
			await applyHqSettings(extensionUri, command.values);
		}
		return;
	}
	const target = findContribution(sourceId);
	if (!target) {
		throw new Error(`No settings contributor registered as ${sourceId}.`);
	}
	await vscode.commands.executeCommand(target.command, command);
}

function findContribution(sourceId: string): CertiqsSettingsContribution | undefined {
	for (const extension of vscode.extensions.all) {
		const raw = extension.packageJSON?.contributes?.certiqsSettings as CertiqsSettingsContribution | undefined;
		if (raw?.id === sourceId && raw.command) {
			return raw;
		}
	}
	return undefined;
}

function isManifest(value: unknown): value is SettingsManifest {
	return Boolean(value && typeof value === 'object' && 'id' in value && 'sections' in value);
}

function isSnapshot(value: unknown): value is SettingsSnapshot {
	return Boolean(value && typeof value === 'object' && 'values' in value && 'secretSet' in value && 'status' in value);
}
