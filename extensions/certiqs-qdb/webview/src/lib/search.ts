// Cohesive client/host-side surface for the advanced search feature. The query
// *engine* (compiler + field→SQL binding) now lives entirely in the Python
// backend (app/search/compile.py, app/search/field_registry.py); the only
// TypeScript the browser and the Next.js route still need is:
//   1. the condition-tree data model (shape the builder edits and the route
//      forwards to Python), and
//   2. the URL codec that makes a query shareable/bookmarkable.
// Field metadata for the picker UI is fetched at runtime from
// GET /api/qsecdb/search/fields (a proxy to the Python /internal/search/fields
// endpoint) — see FieldMeta below — rather than compiled into the bundle, so
// the Drizzle schema no longer ships to the client.

// ── Condition-tree data model ──────────────────────────────────────────────
// The tree shape the client-side builder edits and the Next.js route forwards
// verbatim to the Python compiler, so the two can never drift.

export type Combinator = "AND" | "OR";
export type FieldType = "text" | "enum" | "number" | "date" | "boolean" | "array";

export type Operator =
  | "contains" | "not_contains" | "equals" | "starts_with"             // text
  | "is_any_of" | "is_none_of"                                          // enum
  | "gt" | "gte" | "lt" | "lte" | "between"                             // number
  | "before" | "after" | "on" | "date_between"                         // date
  | "is_true" | "is_false"                                              // boolean
  | "array_contains_any" | "array_contains_all" | "array_contains_none" // array
  | "is_empty" | "is_not_empty";                                       // universal, gated by field.nullable

export interface ConditionValue {
  text?: string;
  values?: string[];
  number?: number;
  numberRange?: [number, number];
  date?: string;            // "yyyy-mm-dd"
  dateRange?: [string, string];
}

export interface Condition {
  id: string;
  kind: "condition";
  field: string;             // key into that domain's field metadata
  operator: Operator;
  value: ConditionValue;
}

export interface ConditionGroup {
  id: string;
  kind: "group";
  combinator: Combinator;
  children: ConditionNode[];
}

export type ConditionNode = Condition | ConditionGroup;

export type SearchDomain = "attacks" | "systems" | "evaluation_activities" | "countermeasures";

export const SEARCH_DOMAINS: readonly SearchDomain[] = [
  "attacks",
  "systems",
  "evaluation_activities",
  "countermeasures",
];

export function isSearchDomain(value: string): value is SearchDomain {
  return (SEARCH_DOMAINS as readonly string[]).includes(value);
}

export const SEARCH_DOMAIN_LABELS: Record<SearchDomain, string> = {
  attacks: "Attacks / Vulnerabilities",
  systems: "Systems",
  evaluation_activities: "Evaluation Activities",
  countermeasures: "Countermeasures",
};

// Hard caps to bound worst-case generated-SQL size, recursive-render depth, and
// shareable-URL length. Enforced both proactively in the UI here and
// authoritatively in the Python compiler (app/search/compile.py).
export const MAX_CONDITIONS = 25;   // total leaf conditions across the whole tree
export const MAX_DEPTH = 5;         // nested group levels, root = depth 1

export function genId(): string {
  return crypto.randomUUID();
}

export function emptyGroup(combinator: Combinator = "AND"): ConditionGroup {
  return { id: genId(), kind: "group", combinator, children: [] };
}

// Starts with no field selected — ConditionRow shows just the field picker
// until the user chooses one, which then fills in a real default operator.
export function emptyCondition(): Condition {
  return { id: genId(), kind: "condition", field: "", operator: "contains", value: {} };
}

export function countLeaves(node: ConditionNode): number {
  if (node.kind === "condition") return 1;
  return node.children.reduce((sum, c) => sum + countLeaves(c), 0);
}

// Measures group nesting only — a leaf condition contributes 0, so a flat root
// group containing only conditions (no nested subgroups) has depth 1, and each
// level of group-within-group adds 1.
export function getDepth(node: ConditionNode): number {
  if (node.kind === "condition") return 0;
  if (node.children.length === 0) return 1;
  return 1 + Math.max(0, ...node.children.map(getDepth));
}

// ── Field metadata (fetched at runtime) ────────────────────────────────────
// The picker-UI view of a searchable field, as served by
// GET /api/qsecdb/search/fields?domain= (proxying Python's
// /internal/search/fields). Deliberately omits the server-only SQL binding
// (column / resolution / family / pgArrayType) that the retired
// src/lib/search/fieldRegistry.ts used to carry — the browser only needs
// labels, types, and value-picker options.

export interface FieldOptions {
  kind: "static" | "lookup";
  values?: readonly string[];
  url?: string;
  valueKey?: string;
  labelKey?: string;
}

export interface FieldMeta {
  key: string;
  label: string;
  group: string;
  type: FieldType;
  nullable: boolean;
  csvMultiValue?: boolean;
  options?: FieldOptions;
}

// ── URL codec ──────────────────────────────────────────────────────────────
// Single shared encode/decode for a ConditionGroup tree to/from a URL
// query-string value, so the address-bar URL and the fetch to the search API
// can never drift onto two different representations.

export function encodeTreeParam(tree: ConditionGroup): string {
  return encodeURIComponent(JSON.stringify(tree));
}

function isCondition(value: unknown): value is Condition {
  if (!value || typeof value !== "object") return false;
  const c = value as Record<string, unknown>;
  return c.kind === "condition" && typeof c.id === "string" && typeof c.field === "string" && typeof c.operator === "string" && typeof c.value === "object" && c.value !== null;
}

function isConditionGroup(value: unknown): value is ConditionGroup {
  if (!value || typeof value !== "object") return false;
  const g = value as Record<string, unknown>;
  if (g.kind !== "group" || typeof g.id !== "string" || (g.combinator !== "AND" && g.combinator !== "OR") || !Array.isArray(g.children)) {
    return false;
  }
  return (g.children as unknown[]).every((child) => isCondition(child) || isConditionGroup(child));
}

// Safe fallback to an empty group on any parse failure or structurally invalid
// shape — a bookmarked/shared URL should degrade gracefully, never crash the page.
export function decodeTreeParam(raw: string | null | undefined): ConditionGroup {
  if (!raw) return emptyGroup();
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(raw));
    return isConditionGroup(parsed) ? parsed : emptyGroup();
  } catch {
    return emptyGroup();
  }
}
