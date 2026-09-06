/**
 * Component-term normalisation for the attack/vulnerability filter chips.
 *
 * Frontend-only display logic: it maps the free-text `attacks.component` column onto
 * canonical `component_types.name` values so the directory and applicability views can
 * group attacks under a component filter. The applicability rules engine does NOT use
 * this - it matches on `component_type_id` via `vulnerability_applicability` scope rows.
 *
 * Mirrored (for reference only) by COMPONENT_SYNONYMS / normalize_component_terms in
 * backend/app/qkd/applicability.py.
 */

// ── Component synonym normalization ──────────────────────────────────────────
// Maps lowercase free-text values from attacks.component → canonical component_types.name.
// A value may be a single string or an array for one-to-many expansion (e.g. generic
// "detector" expands to both SPD and APD so it appears under either filter chip).
export const COMPONENT_SYNONYMS: Record<string, string | string[]> = {
  // → Single-Photon Detector (SNSPD, generic SPD)
  "single photon detector": "Single-Photon Detector",
  "single-photon detector": "Single-Photon Detector",
  "spd": "Single-Photon Detector",
  "snspd": "Single-Photon Detector",
  "superconducting nanowire single-photon detector": "Single-Photon Detector",
  "superconducting nanowire single photon detector": "Single-Photon Detector",
  // → Avalanche Photon Detector (APD subtypes)
  "apd": "Avalanche Photon Detector",
  "avalanche photodiode": "Avalanche Photon Detector",
  "avalanche photon detector": "Avalanche Photon Detector",
  "gated apd": "Avalanche Photon Detector",
  "passively-quenched or negative-feedback apd": "Avalanche Photon Detector",
  "actively-quenched apd": "Avalanche Photon Detector",
  "self-differencing apd": "Avalanche Photon Detector",
  // → both SPD and APD — generic detection terms that cover either detector type
  "detector module": ["Single-Photon Detector", "Avalanche Photon Detector"],
  "detection module": ["Single-Photon Detector", "Avalanche Photon Detector"],
  "detector": ["Single-Photon Detector", "Avalanche Photon Detector"],
  "photodiode": ["Single-Photon Detector", "Avalanche Photon Detector"],
  // → Coherent Detector
  "coherent detector": "Coherent Detector",
  "homodyne detector": "Coherent Detector",
  "heterodyne detector": "Coherent Detector",
  "balanced detector": "Coherent Detector",
  // BSI 4.55's subcomponent line reads "Balanced homodyne detector, beamsplitter"
  "balanced homodyne detector": "Coherent Detector",
  "dc balancing": "Coherent Detector",
  "lo monitor": "Injected Light Monitor",
  "local oscillator monitor": "Injected Light Monitor",
  // → Laser Source
  "laser": "Laser Source",
  "laser source": "Laser Source",
  "laser diode": "Laser Source",
  "light source": "Laser Source",
  "photon source": "Laser Source",
  "pulsed laser": "Laser Source",
  "cw laser": "Laser Source",
  "attenuated laser": "Laser Source",
  // → Phase Modulator
  "phase modulator": "Phase Modulator",
  "pm": "Phase Modulator",
  // → Intensity Modulator
  "intensity modulator": "Intensity Modulator",
  "im": "Intensity Modulator",
  // → both Phase Modulator and Intensity Modulator — generic modulator terms
  "optical modulator": ["Phase Modulator", "Intensity Modulator"],
  "quadrature modulator": ["Phase Modulator", "Intensity Modulator"],
  // BSI 4.54's subcomponent line — the Gaussian modulator is an amplitude+phase pair
  "modulation system": ["Phase Modulator", "Intensity Modulator"],
  // → Attenuator
  "voa": "Attenuator",
  "variable optical attenuator": "Attenuator",
  "attenuator": "Attenuator",
  // → Beam Splitter
  "beam splitter": "Beam Splitter",
  "beamsplitter": "Beam Splitter",
  "bs": "Beam Splitter",
  "fiber coupler": "Beam Splitter",
  "fibre coupler": "Beam Splitter",
  // → Polarisation Component
  "polariser": "Polarisation Component",
  "polarizer": "Polarisation Component",
  "polarisation component": "Polarisation Component",
  "polarization component": "Polarisation Component",
  "pbs": "Polarisation Component",
  "polarising beam splitter": "Polarisation Component",
  "polarizing beam splitter": "Polarisation Component",
  // → Polarization Controller
  "polarisation controller": "Polarization Controller",
  "polarization controller": "Polarization Controller",
  // → Optical Isolator
  "optical isolator": "Optical Isolator",
  "isolator": "Optical Isolator",
  "faraday isolator": "Optical Isolator",
  "circulator": "Optical Isolator",
  // → Injected Light Monitor
  "injected light monitor": "Injected Light Monitor",
  "ilm": "Injected Light Monitor",
  // → Time-Digital Converter
  "time-digital converter": "Time-Digital Converter",
  "time digital converter": "Time-Digital Converter",
  "tdc": "Time-Digital Converter",
  // → Coincidence Matcher
  "coincidence matcher": "Coincidence Matcher",
  "coincidence logic": "Coincidence Matcher",
  // → PP software stages (canonical names from pp_component_types; synonyms handle case/typo variants)
  "public announcements": "Public Announcements",
  "error correction": "Error Correction",
  "error verification": "Error Verification",
  "privacy amplification": "Privacy Amplification",
  "privacy amplifcation": "Privacy Amplification",
  "parameter estimation": "Parameter Estimation",
  "sifting": "Sifting",
  "information reconciliation": "Error Correction",
  "reconciliation": "Error Correction",
  // → all hardware component types — EM radiation leaks from any active hardware element
  "any component emitting electromagnetic radiation": [
    "Laser Source", "Phase Modulator", "Intensity Modulator", "Attenuator",
    "Beam Splitter", "Polarisation Component", "Single-Photon Detector",
    "Avalanche Photon Detector", "Coherent Detector", "Optical Isolator",
    "Time-Digital Converter",
  ],
};

/**
 * Split a comma-separated attacks.component string and map each term to its
 * canonical component_types.name(s).  A synonym may expand to multiple names
 * (e.g. "detection module" → SPD + APD).  Unknown terms fall back to their
 * original value so novel component names still appear in the filter.
 */
export function normalizeComponentTerms(component: string | null): string[] {
  if (!component) return [];
  return [...new Set(
    component
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .flatMap((t) => {
        const mapped = COMPONENT_SYNONYMS[t.toLowerCase()];
        if (Array.isArray(mapped)) return mapped;
        return [mapped ?? t];
      }),
  )];
}
