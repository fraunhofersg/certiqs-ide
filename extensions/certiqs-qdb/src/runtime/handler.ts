/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { ServiceRuntime } from '../serviceRuntime';
import { RuntimeCommand, RuntimeSnapshot } from './types';

export async function handleRuntimeCommand(runtime: ServiceRuntime, command: RuntimeCommand): Promise<RuntimeSnapshot | undefined> {
	if (!command?.type) {
		return;
	}
	switch (command.type) {
		case 'describe':
		case 'status':
			return runtime.snapshot();
		case 'start':
			await runtime.ensureStarted();
			return runtime.snapshot();
		case 'stop':
			await runtime.stop();
			return runtime.snapshot();
		case 'restart':
			await runtime.restart();
			return runtime.snapshot();
		case 'logs':
			runtime.showOutput();
			return runtime.snapshot();
		case 'rebuild':
			await runtime.rebuild();
			return runtime.snapshot();
	}
}
