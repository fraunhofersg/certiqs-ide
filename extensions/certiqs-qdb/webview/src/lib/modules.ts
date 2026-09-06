// Canonical map from module_types.name short codes to the display names used in
// countermeasures.module and attacks.module. Covers all known DB variants.
export const MODULE_SHORT_TO_DISPLAY: Record<string, string> = {
  TX: "Transmitter",
  RX: "Receiver",
  PP: "Post-processing",
  POST_PROCESSING: "Post-processing",
};

// Canonical display order for module filter chips (TX, then RX, then PP), shared by
// AttacksView.tsx and VulnerabilityDirectoryClient.tsx so the two filter UIs can't drift.
export const MODULE_ORDER = ["Transmitter", "Receiver", "Post-processing"];
