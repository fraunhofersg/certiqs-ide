/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Fraunhofer Singapore. All rights reserved.
 *--------------------------------------------------------------------------------------------*/

export type ParamMeta = {
	key: string;
	label: string;
	min: number;
	max: number;
	step: number;
};

export type MetricAssessmentBand = {
	level: string;
	lower: number;
	upper: number;
	label?: string | null;
};

export type MetricAssessmentLine = {
	level: string;
	y: number;
	label?: string | null;
	style?: string | null;
};

export type MetricTechnicalRange = {
	nominal?: number | null;
	good_range?: number[] | null;
	warning_threshold?: number | null;
	abort_threshold?: number | null;
	bands?: MetricAssessmentBand[];
	lines?: MetricAssessmentLine[];
	context?: string | null;
	standard?: string | null;
	label?: string | null;
	contributions?: Record<string, number>;
	lower?: number | null;
	upper?: number | null;
	kind?: string | null;
	upper_label?: string | null;
	lower_label?: string | null;
};

export type MetricCatalogEntry = {
	key: string;
	label: string;
	unit: string;
	kind: string;
	default_plot: boolean;
	technical_range?: MetricTechnicalRange | null;
};

export type MetaResponse = {
	base_params: ParamMeta[];
	attack_params: ParamMeta[];
	selftest_params: ParamMeta[];
	selftest_modes: string[];
	protocols: string[];
	attacks: string[];
	countermeasures: string[];
	default_shots_per_window: number;
};

export type ConfigEntry = {
	name: string;
	defaults?: Record<string, number>;
	error?: string;
};

export type ConfigsResponse = {
	config_root: string;
	default_config: string;
	configs: ConfigEntry[];
};

export type DataPoint = {
	run_id: string;
	epoch: number;
	settings_version: number;
	attack_enabled?: boolean;
	metrics: Record<string, number | null | undefined>;
	wall_time?: number;
};

export type SettingsSnapshot = {
	version: number;
	run_id: string;
	config_name: string;
	protocol: string;
	shots_per_window: number;
	base: Record<string, number>;
	attack: Record<string, unknown>;
	selftest: Record<string, unknown>;
	active_from_epoch?: number;
	manifest_sha256?: string;
};

export type RunStatus = {
	run_id?: string | null;
	status: string;
	error?: string | null;
	protocol?: string | null;
	config_name?: string | null;
	shots_per_window?: number | null;
	epoch?: number | null;
	settings_version?: number | null;
	current_settings?: SettingsSnapshot | null;
	attack_enabled?: boolean | null;
	last_point?: DataPoint | null;
	started_at?: number | null;
	history_size?: number | null;
};

export type StreamMessage =
	| { type: 'catalog'; data: MetricCatalogEntry[] }
	| { type: 'status'; data: RunStatus }
	| { type: 'history'; data: DataPoint[] }
	| { type: 'datapoint'; data: DataPoint }
	| { type: string; data?: unknown };

export type ConfigDocumentEntry = {
	name: string;
	imported: boolean;
	present: boolean;
};

export type ConfigFilesResponse = {
	config: string;
	config_dir: string;
	manifest_file?: string | null;
	manifest_name?: string | null;
	manifest_description?: string | null;
	files: ConfigDocumentEntry[];
};

export type TaxonomyIcon = {
	icon_id?: string;
	file?: string;
	media_type?: string;
	alt_text?: string;
};

export type ComponentClassification = {
	taxonomy_id?: string;
	category_id: string;
	subcategory_id: string;
	category_name?: string;
	subcategory_name?: string;
	icon?: TaxonomyIcon;
};

export type StructuralPath = {
	system_id?: string | null;
	package_id?: string | null;
	node_id?: string | null;
	kms_id?: string | null;
	device_id?: string | null;
	domain_id?: string | null;
	subdomain_id?: string | null;
	module_id?: string | null;
};

export type ComponentInventoryEntry = {
	logical_component_id: string;
	component_class: string;
	domain?: string | null;
	subsystem?: string | null;
	source_file?: string;
	settings?: Record<string, unknown>;
	model_binding_id?: string | null;
	model_kind?: string | null;
	classification?: ComponentClassification | null;
	structural_path?: StructuralPath | null;
};

export type ComponentInventoryResponse = {
	config_dir: string;
	manifest_sha256: string;
	component_count: number;
	unmapped_component_ids?: string[];
	components: ComponentInventoryEntry[];
};

export type TopologyPort = {
	id: string;
	group?: string;
	direction?: string | null;
	signal_type?: string;
	packet_type?: string;
	edge_kind?: string;
	medium?: string;
	source_file?: string;
};

export type TopologyNodePorts = {
	inputs: TopologyPort[];
	outputs: TopologyPort[];
	bidirectional?: TopologyPort[];
};

export type HierarchyGroup = {
	id: string;
	label: string;
	group_kind: string;
	parent_id?: string | null;
	children?: string[];
	member_ids?: string[];
	node_role?: string | null;
	endpoint_side?: string | null;
	lane?: string | null;
	order?: number | null;
	authoritative_host?: boolean | null;
	package_id?: string | null;
	ports?: TopologyNodePorts;
};

export type TopologyGroup = {
	id: string;
	label: string;
	group_kind: string;
	deployment_role?: string | null;
	endpoint_side?: string | null;
	member_ids: string[];
	member_count: number;
	ports?: TopologyNodePorts;
};

export type TopologyNode = {
	id: string;
	label: string;
	node_type: string;
	subsystem?: string | null;
	deployment_role?: string | null;
	endpoint_side?: string | null;
	component_class?: string | null;
	edge_kind?: string | null;
	domain?: string | null;
	source_file?: string;
	model_binding_id?: string | null;
	model_kind?: string | null;
	ports?: TopologyNodePorts;
	connected?: boolean;
};

export type TopologyEdge = {
	id: string;
	source: string;
	target: string;
	source_port?: string | null;
	target_port?: string | null;
	via?: string | null;
	edge_kind: string;
	source_file?: string;
};

export type FrameBoundaryLink = {
	id: string;
	source_frame: string;
	target_frame: string;
	source_port: string;
	target_port: string;
	edge_kind: string;
	channel_id?: string | null;
	via?: string | null;
	source_file?: string | null;
};

export type TopologyResponse = {
	config_dir: string;
	manifest_sha256: string;
	system: { name?: string | null; protocol?: string | null; topology?: string | null };
	node_count: number;
	edge_count: number;
	connected_node_ids?: string[];
	groups?: TopologyGroup[];
	hierarchy?: HierarchyGroup[];
	frame_links?: FrameBoundaryLink[];
	schema_version?: string | null;
	nodes: TopologyNode[];
	edges: TopologyEdge[];
};

export type TaxonomyCategory = {
	category_id: string;
	name: string;
	subcategories: { subcategory_id: string; name: string }[];
};

export type TaxonomyResponse = {
	component_taxonomy: { taxonomy_id: string; name: string; categories: TaxonomyCategory[] };
	config?: string;
};

export type SimTerminalPromptResponse = {
	run_id: string;
	prompt: string;
	ok: boolean;
	output?: string;
	error?: string | null;
	note?: string;
};

export type BootstrapSnapshot = {
	meta: MetaResponse | null;
	catalog: MetricCatalogEntry[];
	configs: ConfigEntry[];
	configName: string;
	status: RunStatus | null;
	points: DataPoint[];
	iconBase?: string;
};
