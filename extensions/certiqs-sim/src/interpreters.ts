/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export const NETSQUID_PYTHON = ['3.8', '3.9', '3.10', '3.11'] as const;

export type InterpreterInfo = {
	path: string;
	version: string;
	minor: string;
	compatible: boolean;
	netsquid?: string;
};

export function listInterpreters(pythonRoot: string, configured: string): InterpreterInfo[] {
	const names = new Set<string>();
	const add = (value?: string) => {
		const trimmed = value?.trim();
		if (trimmed) {
			names.add(trimmed);
		}
	};
	add(configured);
	add('python3');
	add('python');
	for (const name of ['python3.8', 'python3.9', 'python3.10', 'python3.11', 'python3.12', 'python3.13']) {
		add(name);
	}
	add(path.join(pythonRoot, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'));
	const exe = process.platform === 'win32' ? 'python.exe' : 'python';
	for (const found of pathInterpreters(exe)) {
		add(found);
	}
	for (const root of condaRoots()) {
		add(path.join(root, 'certiqs-sim', process.platform === 'win32' ? path.join('Scripts', exe) : path.join('bin', exe)));
		addEnvs(root, exe, add);
	}
	addEnvs(path.join(process.env.HOME ?? '', '.pyenv', 'versions'), exe, add);

	const seen = new Set<string>();
	const found: InterpreterInfo[] = [];
	for (const name of names) {
		const info = probeInterpreter(name);
		if (!info) {
			continue;
		}
		const key = realPath(info.path);
		if (seen.has(key)) {
			continue;
		}
		seen.add(key);
		found.push(info);
	}
	found.sort((a, b) => {
		if (a.compatible !== b.compatible) {
			return a.compatible ? -1 : 1;
		}
		return b.minor.localeCompare(a.minor, undefined, { numeric: true });
	});
	return found;
}

export function probeInterpreter(pythonPath: string): InterpreterInfo | undefined {
	if (pythonPath.includes(path.sep) && !fs.existsSync(pythonPath)) {
		return undefined;
	}
	const version = run(pythonPath, ['-c', 'import sys; print(sys.version.split()[0]); print(f"{sys.version_info.major}.{sys.version_info.minor}")']);
	if (!version) {
		return undefined;
	}
	const [full, minor] = version.split(/\r?\n/);
	if (!full || !minor) {
		return undefined;
	}
	const resolved = which(pythonPath) ?? pythonPath;
	const netsquid = run(resolved, ['-c', 'import netsquid; print(netsquid.__version__)']);
	return {
		path: resolved,
		version: full,
		minor,
		compatible: (NETSQUID_PYTHON as readonly string[]).includes(minor),
		netsquid: netsquid || undefined,
	};
}

function addEnvs(envsRoot: string, exe: string, add: (value?: string) => void): void {
	if (!fs.existsSync(envsRoot)) {
		return;
	}
	const nest = process.platform === 'win32' ? 'Scripts' : 'bin';
	for (const name of fs.readdirSync(envsRoot)) {
		add(path.join(envsRoot, name, nest, exe));
	}
}

function pathInterpreters(exe: string): string[] {
	const names = new Set([exe, 'python3', 'python3.8', 'python3.9', 'python3.10', 'python3.11', 'python3.12', 'python3.13']);
	const found: string[] = [];
	for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
		if (!dir) {
			continue;
		}
		for (const name of names) {
			const candidate = path.join(dir, name);
			if (fs.existsSync(candidate)) {
				found.push(candidate);
			}
		}
	}
	return found;
}

function condaRoots(): string[] {
	const roots = new Set<string>();
	const prefix = process.env.CONDA_PREFIX;
	if (prefix) {
		roots.add(path.join(path.dirname(prefix), 'envs'));
		if (path.basename(prefix) === 'envs' || fs.existsSync(path.join(prefix, 'envs'))) {
			roots.add(path.join(prefix, 'envs'));
		}
	}
	roots.add('/opt/anaconda3/envs');
	roots.add('/opt/miniconda3/envs');
	roots.add(path.join(process.env.HOME ?? '', 'anaconda3', 'envs'));
	roots.add(path.join(process.env.HOME ?? '', 'miniconda3', 'envs'));
	return [...roots];
}

function run(pythonPath: string, args: string[]): string | undefined {
	const result = spawnSync(pythonPath, args, {
		encoding: 'utf8',
		timeout: 4000,
		stdio: ['ignore', 'pipe', 'pipe'],
	});
	if (result.status !== 0) {
		return undefined;
	}
	return (result.stdout ?? '').trim() || undefined;
}

function which(pythonPath: string): string | undefined {
	if (pythonPath.includes(path.sep)) {
		try {
			return fs.realpathSync(pythonPath);
		} catch {
			return pythonPath;
		}
	}
	const result = spawnSync(process.platform === 'win32' ? 'where' : 'which', [pythonPath], {
		encoding: 'utf8',
		timeout: 3000,
		stdio: ['ignore', 'pipe', 'pipe'],
	});
	const first = (result.stdout ?? '').trim().split(/\r?\n/)[0];
	return first || undefined;
}

function realPath(value: string): string {
	try {
		return fs.realpathSync(value);
	} catch {
		return value;
	}
}
