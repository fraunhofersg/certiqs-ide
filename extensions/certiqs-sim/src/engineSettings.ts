/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import * as vscode from 'vscode';
import { ServiceRuntime } from './serviceRuntime';

export const NETSQUID_PASSWORD_KEY = 'certiqs.sim.netsquidPypiPassword';
const DEFAULT_INDEX = 'https://pypi.netsquid.org';

export async function installEngine(context: vscode.ExtensionContext, runtime: ServiceRuntime): Promise<void> {
	const config = vscode.workspace.getConfiguration('certiqs.sim');
	const user = config.get<string>('netsquidPypiUser', '').trim();
	const urlOverride = config.get<string>('netsquidPypiUrl', '').trim();
	const password = ((await context.secrets.get(NETSQUID_PASSWORD_KEY)) ?? '').trim();
	runtime.appendLog(`netsquid settings user=${user} password=${password}`);
	runtime.appendLog(`netsquid override=${urlOverride || '(empty)'}`);
	const indexUrl = buildNetsquidIndexUrl(user, password, urlOverride);
	if (!indexUrl) {
		throw new Error('Store a NetSquid PyPI user and password in certiqs Settings first, then Install NetSquid.');
	}
	runtime.appendLog(`netsquid extra-index-url=${indexUrl}`);
	const before = await runtime.inspectEngine();
	runtime.appendLog(`netsquid target python=${before.pythonVersion} platform=${before.platform} machine=${before.machine}`);
	const majorMinor = before.pythonVersion.split('.').slice(0, 2).join('.');
	if (!['3.8', '3.9', '3.10', '3.11'].includes(majorMinor)) {
		throw new Error(
			`NetSquid has no wheel for Python ${before.pythonVersion} (${before.machine}). Official install is: pip3 install --extra-index-url https://pypi.netsquid.org netsquid — on Python 3.8–3.11. This machine already has NetSquid 1.1.8 in conda env certiqs-sim (3.10). Set Python path to that interpreter, or create a 3.10 venv.`,
		);
	}
	const latest = await runtime.latestNetsquidVersion(indexUrl);
	if (latest) {
		runtime.appendLog(`netsquid latest on index=${latest}`);
	} else {
		runtime.appendLog('netsquid latest on index=unknown; pip will pick the newest wheel for this architecture');
	}
	try {
		await runtime.installPackage(latest ? `netsquid==${latest}` : 'netsquid', indexUrl);
	} catch (error) {
		if (!latest) {
			throw error;
		}
		runtime.appendLog(`netsquid ${latest} has no wheel for python ${before.pythonVersion} ${before.machine}; installing newest compatible wheel`);
		await runtime.installPackage('netsquid', indexUrl);
	}
	const after = await runtime.inspectEngine();
	runtime.appendLog(`netsquid installed version=${after.version ?? 'none'} python=${after.pythonVersion} platform=${after.platform} machine=${after.machine}`);
}

/**
 * Index host comes from the optional override. Username and password always
 * come from Settings — never from placeholder userinfo in the override URL.
 */
export function buildNetsquidIndexUrl(user: string, password: string, override: string): string {
	if (!user || !password) {
		return '';
	}
	const base = override || DEFAULT_INDEX;
	let parsed: URL;
	try {
		parsed = new URL(base.includes('://') ? base : `https://${base}`);
	} catch {
		return '';
	}
	parsed.username = user;
	parsed.password = password;
	// Index root only. /netsquid is the project page; /simple is not this server's layout.
	parsed.pathname = '/';
	parsed.search = '';
	parsed.hash = '';
	return parsed.toString().replace(/\/$/, '');
}
