/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export const DATABASE_URL_KEY = 'certiqs.qdb.databaseUrl';
export const INTERNAL_AUTH_SECRET_KEY = 'certiqs.qdb.internalAuthSecret';
export const NEO4J_PASSWORD_KEY = 'certiqs.qdb.neo4jPassword';
export const ANTHROPIC_KEY = 'certiqs.qdb.anthropicApiKey';
export const VOYAGE_KEY = 'certiqs.qdb.voyageApiKey';
export const AI_GATEWAY_KEY = 'certiqs.qdb.aiGatewayApiKey';

export type QdbEnv = {
	databaseUrl: string;
	internalAuthSecret: string;
	internalAuthTtlSeconds: number;
	neonHttpFallback: boolean;
	neo4jUri: string;
	neo4jUsername: string;
	neo4jPassword: string;
	anthropicApiKey: string;
	voyageApiKey: string;
	aiGatewayApiKey: string;
	aiGatewayBaseUrl: string;
};

export function envForChild(env: QdbEnv): NodeJS.ProcessEnv {
	const next: NodeJS.ProcessEnv = {
		DATABASE_URL: env.databaseUrl,
		INTERNAL_AUTH_SECRET: env.internalAuthSecret,
		INTERNAL_AUTH_TTL_SECONDS: String(env.internalAuthTtlSeconds),
	};
	if (env.neonHttpFallback) {
		next.NEON_HTTP_FALLBACK = '1';
	}
	if (env.neo4jUri) {
		next.NEO4J_URI = env.neo4jUri;
	}
	if (env.neo4jUsername) {
		next.NEO4J_USERNAME = env.neo4jUsername;
	}
	if (env.neo4jPassword) {
		next.NEO4J_PASSWORD = env.neo4jPassword;
	}
	if (env.anthropicApiKey) {
		next.ANTHROPIC_API_KEY = env.anthropicApiKey;
	}
	if (env.voyageApiKey) {
		next.VOYAGE_API_KEY = env.voyageApiKey;
	}
	if (env.aiGatewayApiKey) {
		next.AI_GATEWAY_API_KEY = env.aiGatewayApiKey;
	}
	if (env.aiGatewayBaseUrl) {
		next.AI_GATEWAY_BASE_URL = env.aiGatewayBaseUrl;
	}
	return next;
}
