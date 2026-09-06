/**
 * Framework-agnostic helpers for instantiating components linked to a
 * countermeasure via `countermeasures.component_type_ids`. Shared by
 * SystemWizard.tsx and SystemCreateForm.tsx, which each have their own
 * component/connection shapes and fetch/state plumbing — this module only
 * computes plain data from already-fetched inputs.
 */

/** Minimal shape shared by WizardComponent/ComponentInput for this module's purposes. */
export interface CmTaggedComponent {
  componentTypeId: number | "";
  createdByCmId?: number;
  cmDefaultIntact?: boolean;
}

export interface CmComponentTypeRow {
  typeId: number;
  typeName: string;
  alreadyPresent: boolean;
}

/**
 * Given a CM's linked component_type_ids and a module's existing components,
 * compute the rows to render in the inline panel (one per linked type).
 * Types already present in the module are still listed (flagged, read-only
 * in the UI) so the panel shows full context of what the CM implies.
 */
export function computeCmComponentRows(
  ctIds: number[] | null | undefined,
  existingComponents: CmTaggedComponent[],
  componentTypeNameById: (id: number) => string
): CmComponentTypeRow[] {
  const ids = ctIds ?? [];
  const existingTypeIds = new Set(
    existingComponents.map((c) => c.componentTypeId).filter((id): id is number => id !== "" && id != null)
  );
  return ids.map((typeId) => ({
    typeId,
    typeName: componentTypeNameById(typeId),
    alreadyPresent: existingTypeIds.has(typeId),
  }));
}

/** True if the panel has nothing new to offer (ctIds empty/null, or every type already present). */
export function cmPanelHasNothingToAdd(rows: CmComponentTypeRow[]): boolean {
  return rows.length === 0 || rows.every((r) => r.alreadyPresent);
}

export type CmComponentChoice = "default" | "manual" | "skip";

export interface CmComponentSeed {
  componentTypeId: number;
  componentId: number | "";
  createdByCmId: number;
  cmDefaultIntact: boolean;
}

/**
 * Build the plain-data "seed" for one new component to append, given the
 * user's per-row choice. Each caller spreads this onto its own
 * emptyComponent() to get a full concrete component object.
 */
export function buildCmComponentSeed(
  ctId: number,
  choice: "default" | "manual",
  cmId: number,
  defaultCatalogByTypeId: Record<number, number>
): CmComponentSeed {
  const componentId = choice === "default" ? defaultCatalogByTypeId[ctId] ?? "" : "";
  return {
    componentTypeId: ctId,
    componentId,
    createdByCmId: cmId,
    // Never true at seed time — "default" only becomes intact once the
    // reference-parameter autofill step completes and explicitly asserts it.
    cmDefaultIntact: false,
  };
}

/** "Add All (defaults)" convenience — build seeds for every row not already present. */
export function buildAllDefaultSeeds(
  rows: CmComponentTypeRow[],
  cmId: number,
  defaultCatalogByTypeId: Record<number, number>
): CmComponentSeed[] {
  return rows
    .filter((r) => !r.alreadyPresent)
    .map((r) => buildCmComponentSeed(r.typeId, "default", cmId, defaultCatalogByTypeId));
}

/**
 * Reference-parameter autofill patch builder, a pure transform, no fetch.
 * Mirrors the wizard's original autofillRefParams/autofillByCmId inline
 * logic: separates the variant discriminator value (if any) from ordinary
 * spec fields.
 */
export function buildRefParamPatch(
  rows: { key: string; value: string }[],
  spec: { variant?: { key: string } } | null | undefined
): { specValues: Record<string, string>; variantValue?: string } {
  const specValues: Record<string, string> = {};
  let variantValue: string | undefined;
  for (const r of rows) {
    if (spec?.variant && r.key === spec.variant.key) variantValue = r.value;
    else specValues[r.key] = r.value;
  }
  return variantValue !== undefined ? { specValues, variantValue } : { specValues };
}

/**
 * Removal-safety classification: given a module's full component list (index
 * order matters), the cmId being deselected, and a caller-supplied predicate
 * for "does any connection touch this index", split that CM's created
 * components into ones safe to remove silently vs. ones that need user
 * confirmation (edited away from their default, or wired into a connection).
 */
export function classifyCmComponentsForRemoval(
  components: CmTaggedComponent[],
  cmId: number,
  connectionsTouchingIndex: (ci: number) => boolean
): { safeIndices: number[]; flaggedIndices: number[] } {
  const safeIndices: number[] = [];
  const flaggedIndices: number[] = [];
  components.forEach((c, ci) => {
    if (c.createdByCmId !== cmId) return;
    const edited = !c.cmDefaultIntact;
    const connected = connectionsTouchingIndex(ci);
    if (edited || connected) flaggedIndices.push(ci);
    else safeIndices.push(ci);
  });
  return { safeIndices, flaggedIndices };
}
