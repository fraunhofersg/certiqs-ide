// Canonical value ranges for the `attacks` table fields, per BSI "Implementation
// Attacks against QKD Systems" §3.2 (attack-potential rating scales) and the
// display strings actually used in `attacks.module`. Shared by the vulnerability
// create form (client-side dropdowns) and the vulnerabilities API route
// (server-side validation) so the two can't drift apart.

export const MODULES = ["Transmitter", "Receiver", "Post-processing"] as const;

export const ATTACK_TYPES = ["Active", "Passive", "Mixed"] as const;

export const FEASIBILITY_OPTIONS = [
  "tAttack < 1 day",
  "tAttack < 1 week",
  "tAttack < 2 weeks",
  "tAttack < 1 month",
  "tAttack < 2 months",
  "tAttack < 3 months",
  "tAttack < 4 months",
  "tAttack < 5 months",
  "tAttack < 6 months",
  "tAttack < 9 months",
  "Not practical",
] as const;

export const EXPERTISE_OPTIONS = ["Laymen", "Proficient", "Expert", "Multiple experts"] as const;

export const OPPORTUNITY_OPTIONS = ["Unlimited", "Easy", "Moderate", "Difficult"] as const;

export const EQUIPMENT_OPTIONS = ["Standard", "Specialised", "Bespoke", "Multiple Bespoke", "Non-existent"] as const;

export const ATTACK_RATINGS = ["Basic", "Enhanced Basic", "Moderate", "High", "Beyond High", "Vulnerability"] as const;

// `attacks.module` is a plain text column: a single canonical value, or several
// joined with ", " (e.g. "Transmitter, Receiver"). Splits and validates each token.
export function parseModuleField(value: unknown): { modules: string[] | null; error: string | null } {
  if (value === null || value === undefined || value === "") return { modules: null, error: null };
  if (typeof value !== "string") return { modules: null, error: "module must be a string" };
  const tokens = value.split(",").map(t => t.trim()).filter(Boolean);
  const invalid = tokens.filter(t => !(MODULES as readonly string[]).includes(t));
  if (invalid.length) {
    return { modules: null, error: `Invalid module value(s): ${invalid.join(", ")}. Must be one of: ${MODULES.join(", ")}` };
  }
  return { modules: tokens, error: null };
}

function validateEnum(value: unknown, allowed: readonly string[], fieldName: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string" || !allowed.includes(value)) {
    return `Invalid ${fieldName} value: ${String(value)}. Must be one of: ${allowed.join(", ")}`;
  }
  return null;
}

// Validates the fixed-enum attack fields; returns the first error message found, or null.
export function validateAttackFields(attack: {
  attack_type?: unknown;
  feasibility?: unknown;
  expertise?: unknown;
  opportunity?: unknown;
  equipment?: unknown;
  attack_rating?: unknown;
  module?: unknown;
}): string | null {
  const { error: moduleError } = parseModuleField(attack.module);
  return (
    moduleError ??
    validateEnum(attack.attack_type, ATTACK_TYPES, "attack_type") ??
    validateEnum(attack.feasibility, FEASIBILITY_OPTIONS, "feasibility") ??
    validateEnum(attack.expertise, EXPERTISE_OPTIONS, "expertise") ??
    validateEnum(attack.opportunity, OPPORTUNITY_OPTIONS, "opportunity") ??
    validateEnum(attack.equipment, EQUIPMENT_OPTIONS, "equipment") ??
    validateEnum(attack.attack_rating, ATTACK_RATINGS, "attack_rating") ??
    null
  );
}
