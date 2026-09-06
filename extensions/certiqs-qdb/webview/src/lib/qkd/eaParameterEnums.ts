// Canonical option list for ea_parameters.parameter_type. Shared by the EA
// creation form (client-side dropdown) and the search field registry
// (server-side + client-side), so the two can't drift apart.

export const PARAMETER_TYPES = [
  "Setup Range",
  "Setup Scalar",
  "Step Parameter",
  "Physical Constant",
  "Execution Parameter",
  "Measured Result",
] as const;
