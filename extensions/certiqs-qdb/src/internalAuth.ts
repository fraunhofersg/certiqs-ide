/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

import { createHmac, randomBytes } from 'crypto';

const ALGORITHM = 'HS256';

export function generateInternalAuthSecret(): string {
	return randomBytes(32).toString('base64url');
}

export function signInternalToken(options: {
	userId: string | null;
	isAdmin: boolean;
	secret: string;
	ttlSeconds: number;
	nowSeconds?: number;
}): string {
	const now = options.nowSeconds ?? Math.floor(Date.now() / 1000);
	const header = base64url(JSON.stringify({ alg: ALGORITHM, typ: 'JWT' }));
	const payload = base64url(JSON.stringify({
		sub: options.userId,
		is_admin: options.isAdmin,
		iat: now,
		exp: now + Math.max(1, options.ttlSeconds),
	}));
	const signature = createHmac('sha256', options.secret)
		.update(`${header}.${payload}`)
		.digest('base64url');
	return `${header}.${payload}.${signature}`;
}

function base64url(input: string): string {
	return Buffer.from(input).toString('base64url');
}
