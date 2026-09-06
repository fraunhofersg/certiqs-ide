/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export type InterpreterInfo = {
	path: string;
	version: string;
	minor: string;
	compatible: boolean;
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
	for (const name of ['python3.10', 'python3.11', 'python3.12', 'python3.13']) {
		add(name);
	}
	add(path.join(pythonRoot, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'));
	const found: InterpreterInfo[] = [];
	const seen = new Set<string>();
	for (const name of names) {
		const info = probeInterpreter(name);
		if (info && !seen.has(info.path)) {
			seen.add(info.path);
			found.push(info);
		}
	}
	return found;
}

export function probeInterpreter(candidate: string): InterpreterInfo | undefined {
	if (!candidate) {
		return undefined;
	}
	try {
		if (candidate.includes(path.sep) && !fs.existsSync(candidate)) {
			return undefined;
		}
	} catch {
		return undefined;
	}
	const result = spawnSync(candidate, ['-c', 'import sys; print(sys.executable); print("%d.%d" % sys.version_info[:2])'], {
		encoding: 'utf8',
		timeout: 4000,
	});
	if (result.status !== 0) {
		return undefined;
	}
	const [executable, version] = (result.stdout || '').trim().split(/\r?\n/);
	if (!executable || !version) {
		return undefined;
	}
	const [major] = version.split('.');
	return {
		path: executable,
		version,
		minor: version,
		compatible: Number(major) >= 3,
	};
}
