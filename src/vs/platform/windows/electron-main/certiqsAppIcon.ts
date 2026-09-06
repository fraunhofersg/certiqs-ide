/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import electron from 'electron';
import { existsSync } from 'fs';
import { join } from '../../../base/common/path.js';
import { isLinux, isMacintosh, isWindows } from '../../../base/common/platform.js';

export const CERTIQS_APP_ICON_SETTING = 'certiqs.appIcon';

const APP_ICON_FILES = {
	colorOnWhite: 'color-on-white',
	blackOnWhite: 'black-on-white',
	whiteOnBlack: 'white-on-black',
} as const;

export type CertiqsAppIconId = keyof typeof APP_ICON_FILES;

export function resolveCertiqsAppIconPath(appRoot: string, value: unknown): string | undefined {
	const id = value && value in APP_ICON_FILES ? value as CertiqsAppIconId : 'colorOnWhite';
	const iconPath = join(appRoot, 'resources', 'certiqs', `app-icon-${APP_ICON_FILES[id]}.png`);
	return existsSync(iconPath) ? iconPath : undefined;
}

export function applyCertiqsAppIcon(win: electron.BrowserWindow | null | undefined, appRoot: string, value: unknown): void {
	const iconPath = resolveCertiqsAppIconPath(appRoot, value);
	if (!iconPath) {
		return;
	}
	const image = electron.nativeImage.createFromPath(iconPath);
	if (image.isEmpty()) {
		return;
	}
	if (isMacintosh) {
		electron.app.dock?.setIcon(image);
	}
	if (win && (isWindows || isLinux)) {
		win.setIcon(image);
	}
}
