// ─────────────────────────────────────────────────────────────────────────────
// Canonical component-parameter dictionary.
//
// Single source of truth for the structured, unit-labelled parameter fields that
// appear per component type. Consumed by:
//   1. SystemCreateForm  — renders the right fields when a component type is picked.
//   2. POST /api/qsecdb/systems — validates/coerces values + stamps the canonical unit.
//   3. (future) the JSON/YAML/CSV import pipeline — verifies & aligns user uploads.
//
// Storage stays relational: every field below maps to one `component_parameters`
// row keyed by its snake_case `key`, so simulation can run
//   SELECT value_num FROM component_parameters WHERE key = 'mean_photon_number'.
//
// `componentType` MUST match a `component_types.name` row (see seed-component-types.ts).
// Keys are stable machine identifiers (snake_case); `label`/`unit` are presentation.
// Omit `unit` for dimensionless / unitless quantities.
// ─────────────────────────────────────────────────────────────────────────────

export type ParamFieldType = "number" | "text" | "select" | "boolean";

export interface ParamField {
  /** Canonical snake_case key → stored in component_parameters.key */
  key: string;
  /** Human-readable label shown in the form */
  label: string;
  /** Canonical unit → stored in component_parameters.unit (omit = unitless) */
  unit?: string;
  type: ParamFieldType;
  /** Allowed values for type "select" */
  options?: string[];
  /** param_group bucket (defaults to "parameters") */
  group?: string;
  /** Optional helper/tooltip text */
  description?: string;
}

export interface VariantSpec {
  /** Discriminator key, e.g. "detector_variant" (stored under group "settings") */
  key: string;
  label: string;
  options: string[];
  /** Extra fields revealed for each variant option */
  fieldsByVariant: Record<string, ParamField[]>;
}

export interface ComponentParamSpec {
  /** Must equal a component_types.name row */
  componentType: string;
  /** Shown for every variant */
  commonFields: ParamField[];
  /** Optional variant discriminator */
  variant?: VariantSpec;
}

export const DEFAULT_PARAM_GROUP = "parameters";
export const VARIANT_PARAM_GROUP = "settings";
// "annotations" is a display-only bucket for free-form user notes.
// No pipeline process (applicability engine, simulation, import) may read or
// act on rows where param_group = 'annotations'.

// ─── Reusable field fragments ────────────────────────────────────────────────
const operatingWavelength: ParamField = {
  key: "operating_wavelength", label: "Operating wavelength", unit: "nm", type: "number",
  description: "Photon wavelength the component is designed for; typically 1310 nm or 1550 nm for telecom-band QKD. Must match the channel and detector sensitivity band.",
};
const insertionLoss: ParamField = {
  key: "insertion_loss", label: "Insertion loss", unit: "dB", type: "number",
  description: "Signal power lost passing through the component (dB). Excess loss reduces the photon flux reaching the detector and lowers the achievable key rate.",
};
const extinctionRatio: ParamField = {
  key: "extinction_ratio", label: "Extinction ratio", unit: "dB", type: "number",
  description: "Ratio of maximum to minimum transmitted intensity (dB). Low extinction increases QBER by allowing wrong-basis photons to partially transmit.",
};
// Shared by every free-running APD variant (and by "SD APD", which adds a gate
// frequency on top) — the quenching mode changes which attacks the applicability
// engine considers, not which parameters the detector exposes.
//
// Every consumer spreads it (`[...freeRunningApdFields]`) rather than referencing it,
// so an in-place edit to one variant's fields can't reach through a shared array and
// mutate the others'.
const freeRunningApdFields: readonly ParamField[] = [
  {
    key: "afterpulse_probability", label: "Afterpulse probability", type: "number",
    description: "Probability of a spurious count triggered by charge trapping from a previous detection (0–1). Contributes to QBER in high repetition-rate systems.",
  },
  {
    key: "operating_temperature", label: "Operating temperature", unit: "°C", type: "number",
    description: "Detector operating temperature. APDs typically require cooling to −30 °C or below to suppress dark counts.",
  },
];

// ─── Specs, keyed by component_types.name ────────────────────────────────────
export const COMPONENT_PARAM_SPECS: Record<string, ComponentParamSpec> = {
  // ── TX optical source. In most QKD systems the "single-photon source" is an
  //    attenuated laser source, so the user's source fields live here. ──
  "Laser Source": {
    componentType: "Laser Source",
    commonFields: [
      {
        key: "optical_pulse_repetition_rate", label: "Optical pulse repetition rate", unit: "Hz", type: "number",
        description: "Rate at which optical pulses are emitted; sets the raw symbol rate of the QKD link.",
      },
      {
        key: "mean_photon_number", label: "Mean photon number", unit: "photons/pulse", type: "number",
        description: "Average photons per pulse after attenuation (typically 0.1–0.5). Must be well below 1 to approximate a single-photon source and bound photon-number-splitting attacks.",
      },
      {
        key: "source_power", label: "Source power", unit: "W", type: "number",
        description: "Optical output power of the laser before attenuation.",
      },
      {
        key: "long_term_power_stability", label: "Long-term power stability", unit: "dB/hr", type: "number",
        description: "Power drift rate over hours (dB/hr). Instability can cause undetected changes in mean photon number, undermining decoy-state security.",
      },
      {
        key: "short_term_power_stability", label: "Short-term power stability", unit: "dB", type: "number",
        description: "Pulse-to-pulse power variation (dB). Affects QBER and the accuracy of decoy-state intensity estimation.",
      },
      {
        key: "source_emission_temporal_profile", label: "Source emission temporal profile", type: "text",
        description: "Shape of the optical pulse envelope — e.g. Gaussian, sech², square. Determines inter-symbol interference and timing-jitter sensitivity.",
      },
      {
        key: "source_timing_jitter", label: "Source timing jitter", unit: "s", type: "number",
        description: "Uncertainty in photon emission time. Limits the achievable timing resolution and the width of detector coincidence windows.",
      },
      {
        key: "center_wavelength", label: "Center wavelength", unit: "nm", type: "number",
        description: "Peak emission wavelength. Must match the QKD channel passband and detector sensitivity range.",
      },
      {
        key: "spectral_linewidth", label: "Spectral linewidth", unit: "nm", type: "number",
        description: "Width of the optical spectrum. Narrow linewidth reduces chromatic dispersion in fibre and improves out-of-band noise filtering.",
      },
    ],
  },

  "Phase Modulator": {
    componentType: "Phase Modulator",
    commonFields: [
      {
        key: "half_wave_voltage_vpi", label: "Half-wave voltage (Vπ)", unit: "V", type: "number",
        description: "Drive voltage required to produce a π phase shift. Lower Vπ allows lower-voltage electronics and reduces drive power requirements.",
      },
      {
        key: "modulation_bandwidth", label: "Modulation bandwidth", unit: "Hz", type: "number",
        description: "Maximum frequency at which the modulator can encode phase. Must exceed the QKD pulse repetition rate.",
      },
      insertionLoss,
      extinctionRatio,
    ],
  },

  "Intensity Modulator": {
    componentType: "Intensity Modulator",
    commonFields: [
      extinctionRatio,
      {
        key: "modulation_bandwidth", label: "Modulation bandwidth", unit: "Hz", type: "number",
        description: "Maximum frequency at which intensity can be switched. Must support both the pulse rate and the decoy-state switching speed.",
      },
      insertionLoss,
      {
        key: "number_of_intensity_levels", label: "Number of intensity levels", type: "number",
        description: "Number of distinct output power levels used — e.g. 3 for signal + 2 decoy intensities. Determines the complexity of the decoy-state protocol.",
      },
    ],
  },

  "Attenuator": {
    componentType: "Attenuator",
    commonFields: [
      {
        key: "attenuation", label: "Attenuation", unit: "dB", type: "number",
        description: "Nominal attenuation applied to reduce the source output to the target mean photon number.",
      },
      {
        key: "max_attenuation", label: "Max attenuation", unit: "dB", type: "number",
        description: "Maximum achievable attenuation. Must be sufficient to reach the target µ at the highest source power.",
      },
      {
        key: "attenuation_accuracy", label: "Attenuation accuracy", unit: "dB", type: "number",
        description: "Uncertainty in actual vs. set attenuation (dB). Inaccuracy causes the mean photon number to deviate from its target, affecting PNS attack bounds.",
      },
      insertionLoss,
    ],
  },

  "Optical Isolator": {
    componentType: "Optical Isolator",
    commonFields: [
      {
        key: "isolation", label: "Isolation", unit: "dB", type: "number",
        description: "Attenuation of backward-propagating light (dB). Values ≥ 30 dB are required to suppress Trojan-horse back-injection and detector-blinding reflections.",
      },
      insertionLoss,
      operatingWavelength,
    ],
  },

  // ── Shared passive optics ──
  "Beam Splitter": {
    componentType: "Beam Splitter",
    commonFields: [
      {
        key: "splitting_ratio", label: "Splitting ratio", type: "text",
        description: 'Power split between output ports — e.g. "50:50" for a balanced splitter or "90:10" for a tap. Determines basis selection probability in passive-choice receivers.',
      },
      insertionLoss,
      operatingWavelength,
    ],
  },

  "Polarisation Component": {
    componentType: "Polarisation Component",
    commonFields: [
      extinctionRatio,
      insertionLoss,
      operatingWavelength,
    ],
  },

  "Polarization Controller": {
    componentType: "Polarization Controller",
    commonFields: [
      extinctionRatio,
      {
        key: "response_time", label: "Response time", unit: "s", type: "number",
        description: "Time to stabilise to a new polarisation state. Slow response causes QBER spikes during channel polarisation drift events.",
      },
      insertionLoss,
    ],
  },

  "Half-Wave Plate": {
    componentType: "Half-Wave Plate",
    commonFields: [
      {
        key: "retardance", label: "Retardance", unit: "waves", type: "number",
        description: "Phase retardance between fast and slow axes in units of wavelengths — e.g. 0.5 for a half-wave plate. Determines the polarisation rotation applied.",
      },
      operatingWavelength,
      insertionLoss,
    ],
  },

  "Compensation Crystal": {
    componentType: "Compensation Crystal",
    commonFields: [
      {
        key: "material", label: "Material", type: "text",
        description: "Birefringent crystal material — e.g. YVO₄, calcite. Determines the birefringence magnitude and temperature sensitivity.",
      },
      {
        key: "crystal_length", label: "Crystal length", unit: "mm", type: "number",
        description: "Physical length of the crystal (mm). Determines the magnitude of birefringence compensation applied to the photon pairs.",
      },
      operatingWavelength,
    ],
  },

  "Faraday Mirror": {
    componentType: "Faraday Mirror",
    commonFields: [
      {
        key: "faraday_rotation_deviation", label: "Faraday rotation deviation", unit: "deg", type: "number",
        description: "Deviation from the ideal 45° single-pass rotation (90° round trip). Non-zero deviation leaves a residual polarisation dependence that a passive eavesdropper can exploit; alignment procedures aim to minimise this value.",
      },
      {
        key: "polarization_extinction_ratio", label: "Polarisation extinction ratio", unit: "dB", type: "number",
        description: "Ratio of the desired to unwanted polarisation component after the round trip. Low extinction indicates residual mirror imperfections that couple polarisation information into the phase-encoded signal.",
      },
      insertionLoss,
      operatingWavelength,
    ],
  },

  // ── EB-QKD source components ───────────────────────────────────────────────

  "Entangled Photon Source": {
    componentType: "Entangled Photon Source",
    commonFields: [
      {
        key: "output_wavelength", label: "Output wavelength", unit: "nm", type: "number",
        description: "Wavelength of the entangled photon pairs emitted toward Alice and Bob.",
      },
      {
        key: "pump_wavelength", label: "Pump wavelength", unit: "nm", type: "number",
        description: "Wavelength of the pump laser driving pair generation; typically half the output wavelength for degenerate SPDC.",
      },
      {
        key: "pair_generation_rate", label: "Pair generation rate", unit: "Mio pairs/s", type: "number",
        description: "Number of entangled photon pairs generated per second; governs the raw coincidence rate.",
      },
      {
        key: "heralding_efficiency", label: "Heralding efficiency", unit: "%", type: "number",
        description: "Fraction of pairs where detecting one photon heralds the presence of the partner (0–100%). Low values increase the multi-photon contribution and raise the QBER.",
      },
      {
        key: "entanglement_fidelity", label: "Entanglement fidelity", unit: "%", type: "number",
        description: "Fidelity of the generated state to the ideal Bell state (0–100%). Low fidelity directly inflates QBER and can invalidate security proofs.",
      },
      {
        key: "spectral_bandwidth", label: "Spectral bandwidth", unit: "nm", type: "number",
        description: "Bandwidth of the generated paired photons. Broader bandwidth increases pair rate but degrades spectral correlations and requires wider-bandwidth filtering.",
      },
      {
        key: "long_term_stability", label: "Long-term stability", unit: "dB/hr", type: "number",
        description: "Drift of pair generation rate over hours. Instability can cause undetected changes in the quantum bit error rate.",
      },
    ],
  },

  "SPDC Nonlinear Crystal": {
    componentType: "SPDC Nonlinear Crystal",
    commonFields: [
      {
        key: "material", label: "Crystal material", type: "text",
        description: "Nonlinear crystal material — e.g. PPKTP, BBO, PPLN, KTP. Determines conversion efficiency, phase-matching bandwidth, and thermal stability.",
      },
      {
        key: "phase_matching_type", label: "Phase-matching type", type: "select", options: ["type-I", "type-II", "type-0"],
        description: "Geometry of the nonlinear interaction. Type-II produces polarisation-entangled pairs directly; type-0/I require additional polarisation optics.",
      },
      {
        key: "pump_wavelength", label: "Pump wavelength", unit: "nm", type: "number",
        description: "Wavelength of the pump laser input to the crystal.",
      },
      {
        key: "signal_wavelength", label: "Signal wavelength", unit: "nm", type: "number",
        description: "Wavelength of the signal output photon.",
      },
      {
        key: "idler_wavelength", label: "Idler wavelength", unit: "nm", type: "number",
        description: "Wavelength of the idler output photon. Signal and idler photon energies sum to match the pump photon energy.",
      },
      {
        key: "poling_period", label: "Poling period", unit: "µm", type: "number",
        description: "Quasi-phase-matching period (PPKTP / PPLN only). Determines the phase-matched wavelength at a given operating temperature.",
      },
      {
        key: "crystal_length", label: "Crystal length", unit: "mm", type: "number",
        description: "Physical length of the crystal (mm). Longer crystals increase brightness but narrow the spectral bandwidth of the generated pairs.",
      },
      {
        key: "brightness", label: "Brightness", unit: "pairs/s/mW/nm", type: "number",
        description: "Pair generation rate per unit pump power per unit bandwidth. Higher brightness enables higher key rates at lower pump powers.",
      },
    ],
  },

  // ── RX detectors ──
  "Single-Photon Detector": {
    componentType: "Single-Photon Detector",
    commonFields: [
      {
        key: "detection_efficiency", label: "Detection efficiency", type: "number",
        description: "Probability of registering a click given an incident photon (0–1). Higher efficiency increases key rate but typically increases dark counts and timing jitter.",
      },
      {
        key: "dark_count_rate", label: "Dark count rate", unit: "cps", type: "number",
        description: "Rate of spurious detection events with no incident photon (counts/s). Contributes directly to QBER and limits the signal-to-noise ratio.",
      },
      {
        key: "dead_time", label: "Dead time", unit: "s", type: "number",
        description: "Minimum interval between detectable events. Limits the maximum count rate and creates blind windows that time-shift attacks can exploit.",
      },
      {
        key: "timing_jitter", label: "Timing jitter", unit: "s", type: "number",
        description: "Uncertainty in the registered photon arrival time. Limits achievable timing resolution and the usable coincidence window in time-bin protocols.",
      },
      operatingWavelength,
    ],
    variant: {
      key: "detector_variant",
      label: "Detector variant",
      // These strings are the keys of VARIANT_TO_DET_TYPE in
      // backend/app/qkd/applicability.py — the applicability engine reads them to decide
      // which detector-control attacks apply. An APD has two independent axes: gating
      // (gated vs free-running) and quenching (actively vs passively quenched), and BSI
      // catalogues an attack per combination. Plain "APD (free-running)" leaves quenching
      // unstated, which makes the engine report BOTH quenching attacks as applicable;
      // pick one of the two explicit variants to narrow that down.
      options: [
        "APD (gated)",
        "APD (free-running)",
        "APD (free-running, actively quenched)",
        "APD (free-running, passively quenched)",
        "SD APD",
        "SNSPD",
        "TES",
      ],
      fieldsByVariant: {
        "APD (gated)": [
          {
            key: "gate_frequency", label: "Gate frequency", unit: "Hz", type: "number",
            description: "Rate at which the APD is enabled. Must synchronise precisely with the QKD pulse train.",
          },
          {
            key: "gate_width", label: "Gate width", unit: "s", type: "number",
            description: "Duration of each detection window. Shorter gates reduce dark counts but require tighter timing synchronisation.",
          },
          {
            key: "afterpulse_probability", label: "Afterpulse probability", type: "number",
            description: "Probability of a spurious count triggered by charge trapping from a previous detection (0–1). Contributes to QBER in high repetition-rate systems.",
          },
          {
            key: "operating_temperature", label: "Operating temperature", unit: "°C", type: "number",
            description: "Detector operating temperature. APDs typically require cooling to −30 °C or below to suppress dark counts.",
          },
        ],
        "APD (free-running)": [...freeRunningApdFields],
        "APD (free-running, actively quenched)": [...freeRunningApdFields],
        "APD (free-running, passively quenched)": [...freeRunningApdFields],
        // Self-differencing APDs are free-running APDs read out through a gate, so
        // they carry the shared fields plus their own gate frequency (whose
        // description differs from the gated variant's).
        "SD APD": [
          {
            key: "gate_frequency", label: "Gate frequency", unit: "Hz", type: "number",
            description: "Rate at which the APD is enabled. Self-differencing APDs are gated at GHz rates, with the previous gate's response subtracted to reveal the avalanche.",
          },
          ...freeRunningApdFields,
        ],
        "TES": [
          {
            key: "operating_temperature", label: "Operating temperature", unit: "K", type: "number",
            description: "Cryogenic operating temperature. Transition-edge sensors are biased within their superconducting transition, typically below 100 mK.",
          },
          {
            key: "reset_time", label: "Reset time", unit: "s", type: "number",
            description: "Thermal recovery time after a detection event before the sensor can register another photon. TES reset times are far longer than APD dead times.",
          },
        ],
        "SNSPD": [
          {
            key: "operating_temperature", label: "Operating temperature", unit: "K", type: "number",
            description: "Cryogenic operating temperature. SNSPDs typically operate at 0.8–4 K using a closed-cycle refrigerator.",
          },
          {
            key: "reset_time", label: "Reset time", unit: "s", type: "number",
            description: "Time after a detection event before the SNSPD can reliably detect again (nanowire recovery time).",
          },
          {
            key: "max_count_rate", label: "Max count rate", unit: "cps", type: "number",
            description: "Maximum sustainable detection rate before dead-time losses become significant.",
          },
          {
            key: "bias_current", label: "Bias current", unit: "µA", type: "number",
            description: "DC current setting the operating point on the SNSPD switching curve. Determines the trade-off between efficiency and dark count rate.",
          },
        ],
      },
    },
  },

  "Coherent Detector": {
    componentType: "Coherent Detector",
    commonFields: [
      {
        key: "detection_scheme", label: "Detection scheme", type: "select", options: ["homodyne", "heterodyne"], group: VARIANT_PARAM_GROUP,
        description: "Measurement basis — homodyne measures one quadrature (X or P); heterodyne measures both simultaneously at a 3 dB SNR penalty.",
      },
      {
        key: "quantum_efficiency", label: "Quantum efficiency", type: "number",
        description: "Photodiode conversion efficiency (0–1). Determines the shot-noise-limited SNR of the balanced detector.",
      },
      {
        key: "electronic_noise", label: "Electronic noise", unit: "shot-noise units", type: "number",
        description: "Detector noise floor relative to shot noise. Values ≥ 1 indicate thermal noise dominates, which can compromise CV-QKD security proofs.",
      },
      {
        key: "detection_bandwidth", label: "Detection bandwidth", unit: "Hz", type: "number",
        description: "RF bandwidth of the balanced detector. Must exceed the modulation bandwidth of the transmitted CV signal.",
      },
      {
        key: "clearance", label: "Clearance", unit: "dB", type: "number",
        description: "Ratio of shot noise to electronic noise (dB). Typically ≥ 10 dB is required for secure CV-QKD key generation.",
      },
      {
        key: "local_oscillator_power", label: "Local oscillator power", unit: "mW", type: "number",
        description: "Optical power of the LO beam. Higher LO power increases shot noise relative to electronic noise, improving clearance.",
      },
    ],
  },

  "Injected Light Monitor": {
    componentType: "Injected Light Monitor",
    commonFields: [
      {
        key: "detection_threshold_power", label: "Detection threshold power", unit: "W", type: "number",
        description: "Minimum optical power level that triggers an alarm. Should be set below the power level where injected light can influence detector behaviour.",
      },
      {
        key: "response_time", label: "Response time", unit: "s", type: "number",
        description: "Time to respond to an injection event. Shorter response limits the duration window of a successful blinding attack.",
      },
      operatingWavelength,
    ],
  },

  "Time-Digital Converter": {
    componentType: "Time-Digital Converter",
    commonFields: [
      {
        key: "time_resolution", label: "Time resolution", unit: "s", type: "number",
        description: "Smallest resolvable time interval (s). Determines timestamp precision and limits timing-jitter compensation capability.",
      },
      {
        key: "dead_time", label: "Dead time", unit: "s", type: "number",
        description: "Minimum interval between consecutive registered events. Creates blind spots that time-shift attacks can exploit.",
      },
      {
        key: "number_of_channels", label: "Number of channels", type: "number",
        description: "Number of independent timing input channels. One channel per detector is required.",
      },
    ],
  },

  "Coincidence Matcher": {
    componentType: "Coincidence Matcher",
    commonFields: [
      {
        key: "coincidence_window", label: "Coincidence window", unit: "s", type: "number",
        description: "Maximum Alice–Bob detection time difference counted as a coincident pair (s). Must be wider than system timing jitter but narrow enough to reject accidental coincidences.",
      },
      {
        key: "number_of_channels", label: "Number of channels", type: "number",
        description: "Number of independent input channels. At least 2 are required for EB-QKD (one per Alice, one per Bob).",
      },
    ],
  },

  // ── TX/RX control electronics ─────────────────────────────────────────────

  "FPGA / System Controller (TX)": {
    componentType: "FPGA / System Controller (TX)",
    commonFields: [
      {
        key: "clock_frequency", label: "System clock frequency", unit: "Hz", type: "number",
        description: "Master system clock rate (Hz). Must be stable and synchronised with the partner node clock for accurate time-tagging.",
      },
      {
        key: "firmware_version", label: "Firmware version", type: "text",
        description: "Semantic version identifier of the loaded firmware. Required for traceability and security patch management.",
      },
      {
        key: "configuration_interface", label: "Configuration interface", type: "select",
        options: ["JTAG", "SPI", "I2C", "Ethernet", "USB"],
        description: "Interface used to load or update firmware. Determines the attack surface for unauthorised firmware modification.",
      },
      {
        key: "logic_cells", label: "Logic cells", type: "number",
        description: "Total FPGA logic capacity (LUTs / ALMs). Determines the headroom available for additional processing or security modules.",
      },
    ],
  },

  "FPGA / System Controller (RX)": {
    componentType: "FPGA / System Controller (RX)",
    commonFields: [
      {
        key: "clock_frequency", label: "System clock frequency", unit: "Hz", type: "number",
        description: "Master system clock rate (Hz). Must be stable and synchronised with the partner node clock for accurate time-tagging.",
      },
      {
        key: "firmware_version", label: "Firmware version", type: "text",
        description: "Semantic version identifier of the loaded firmware. Required for traceability and security patch management.",
      },
      {
        key: "configuration_interface", label: "Configuration interface", type: "select",
        options: ["JTAG", "SPI", "I2C", "Ethernet", "USB"],
        description: "Interface used to load or update firmware. Determines the attack surface for unauthorised firmware modification.",
      },
      {
        key: "logic_cells", label: "Logic cells", type: "number",
        description: "Total FPGA logic capacity (LUTs / ALMs). Determines the headroom available for additional processing or security modules.",
      },
    ],
  },

  "Clock Synthesizer (TX)": {
    componentType: "Clock Synthesizer (TX)",
    commonFields: [
      {
        key: "output_frequency", label: "Output frequency", unit: "Hz", type: "number",
        description: "Clock frequency delivered to the QKD system. Must match the link pulse repetition rate.",
      },
      {
        key: "reference_frequency", label: "Reference frequency", unit: "Hz", type: "number",
        description: "External reference input frequency (omit if free-running). Sets the disciplining source for the synthesiser PLL.",
      },
      {
        key: "timing_jitter", label: "Timing jitter (RMS)", unit: "s", type: "number",
        description: "RMS timing uncertainty of the synthesised clock (s). Directly contributes to overall system timing jitter and the width of the coincidence window.",
      },
      {
        key: "phase_noise", label: "Phase noise @ 10 kHz offset", unit: "dBc/Hz", type: "number",
        description: "Spectral purity at 10 kHz offset (dBc/Hz). High phase noise creates timing uncertainty that widens the coincidence window and increases accidental coincidences.",
      },
      {
        key: "synchronization_mode", label: "Synchronization mode", type: "select",
        options: ["internal", "external", "GPS-disciplined"],
        description: "How the clock is referenced — internal free-running, locked to an external reference, or GPS-disciplined for long-distance links.",
      },
    ],
  },

  "Clock Synthesizer (RX)": {
    componentType: "Clock Synthesizer (RX)",
    commonFields: [
      {
        key: "output_frequency", label: "Output frequency", unit: "Hz", type: "number",
        description: "Clock frequency delivered to the QKD system. Must match the link pulse repetition rate.",
      },
      {
        key: "reference_frequency", label: "Reference frequency", unit: "Hz", type: "number",
        description: "External reference input frequency (omit if free-running). Sets the disciplining source for the synthesiser PLL.",
      },
      {
        key: "timing_jitter", label: "Timing jitter (RMS)", unit: "s", type: "number",
        description: "RMS timing uncertainty of the synthesised clock (s). Directly contributes to overall system timing jitter and the width of the coincidence window.",
      },
      {
        key: "phase_noise", label: "Phase noise @ 10 kHz offset", unit: "dBc/Hz", type: "number",
        description: "Spectral purity at 10 kHz offset (dBc/Hz). High phase noise creates timing uncertainty that widens the coincidence window and increases accidental coincidences.",
      },
      {
        key: "synchronization_mode", label: "Synchronization mode", type: "select",
        options: ["internal", "external", "GPS-disciplined"],
        description: "How the clock is referenced — internal free-running, locked to an external reference, or GPS-disciplined for long-distance links.",
      },
    ],
  },

  "RF Driver (TX)": {
    componentType: "RF Driver (TX)",
    commonFields: [
      {
        key: "bandwidth", label: "Bandwidth", unit: "Hz", type: "number",
        description: "Frequency range over which the driver delivers full output power. Must exceed the highest required modulation frequency.",
      },
      {
        key: "output_voltage_swing", label: "Output voltage swing (Vpp)", unit: "V", type: "number",
        description: "Peak-to-peak voltage delivered to the modulator. Must meet or exceed the modulator's Vπ to achieve full extinction.",
      },
      {
        key: "rise_time", label: "Rise time (10–90%)", unit: "s", type: "number",
        description: "10–90% transition time of the output pulse. Fast rise times sharply define modulation windows and reduce inter-symbol interference.",
      },
      {
        key: "gain", label: "Gain", unit: "dB", type: "number",
        description: "Signal amplification (dB). Determines the drive level delivered to the modulator.",
      },
    ],
  },

  "RF Driver (RX)": {
    componentType: "RF Driver (RX)",
    commonFields: [
      {
        key: "bandwidth", label: "Bandwidth", unit: "Hz", type: "number",
        description: "Frequency range over which the driver delivers full output power. Must exceed the highest required modulation frequency.",
      },
      {
        key: "output_voltage_swing", label: "Output voltage swing (Vpp)", unit: "V", type: "number",
        description: "Peak-to-peak voltage delivered to the modulator. Must meet or exceed the modulator's Vπ to achieve full extinction.",
      },
      {
        key: "rise_time", label: "Rise time (10–90%)", unit: "s", type: "number",
        description: "10–90% transition time of the output pulse. Fast rise times sharply define modulation windows and reduce inter-symbol interference.",
      },
      {
        key: "gain", label: "Gain", unit: "dB", type: "number",
        description: "Signal amplification (dB). Determines the drive level delivered to the modulator.",
      },
    ],
  },
};

// ─── Lookup (tolerant of case / surrounding whitespace) ──────────────────────
const NORMALIZED_INDEX: Record<string, ComponentParamSpec> = (() => {
  const idx: Record<string, ComponentParamSpec> = {};
  for (const spec of Object.values(COMPONENT_PARAM_SPECS)) {
    idx[spec.componentType.trim().toLowerCase()] = spec;
  }
  // "Avalanche Photon Detector" is merged into Single-Photon Detector as APD variants.
  // The component_type row is kept in the DB for vulnerability_applicability FK references,
  // but the form no longer offers it as a standalone type.
  idx["avalanche photon detector"] = idx["single-photon detector"];
  return idx;
})();

export function getSpecForComponentType(name: string | undefined | null): ComponentParamSpec | undefined {
  if (!name) return undefined;
  return NORMALIZED_INDEX[name.trim().toLowerCase()];
}

/** Flatten the spec fields visible for a given variant selection (common + variant). */
export function fieldsForSpec(spec: ComponentParamSpec, variantValue?: string): ParamField[] {
  const fields = [...spec.commonFields];
  if (spec.variant && variantValue && spec.variant.fieldsByVariant[variantValue]) {
    fields.push(...spec.variant.fieldsByVariant[variantValue]);
  }
  return fields;
}

// ─── Context metadata for wizard filtering ───────────────────────────────────
// Used by SystemWizard to pre-filter component type chips by encoding / architecture.
// Omit a key to mean "applicable to all values of that dimension."
export interface ComponentTypeContext {
  encodings?: ("DV" | "CV")[];
  architectures?: ("PM" | "MDI" | "EB")[];
}

export const COMPONENT_TYPE_CONTEXT: Record<string, ComponentTypeContext> = {
  "Laser Source":              {},
  "Phase Modulator":           {},
  "Intensity Modulator":       {},
  "Attenuator":                {},
  "Optical Isolator":          {},
  "Beam Splitter":             {},
  "Polarisation Component":    { encodings: ["DV"] },
  "Polarization Controller":   { encodings: ["DV"] },
  "Half-Wave Plate":           { encodings: ["DV"] },
  "Compensation Crystal":      { architectures: ["EB"] },
  "Faraday Mirror":            { encodings: ["DV"] },
  "Entangled Photon Source":   { architectures: ["EB"] },
  "SPDC Nonlinear Crystal":    { architectures: ["EB"] },
  "Single-Photon Detector":    { encodings: ["DV"] },
  "Avalanche Photon Detector": { encodings: ["DV"] },
  "Coherent Detector":         { encodings: ["CV"] },
  "Injected Light Monitor":    {},
  "Time-Digital Converter":    {},
  "Coincidence Matcher":       { architectures: ["EB"] },
  "FPGA / System Controller (TX)": {},
  "FPGA / System Controller (RX)": {},
  "Clock Synthesizer (TX)":        {},
  "Clock Synthesizer (RX)":        {},
  "RF Driver (TX)":                {},
  "RF Driver (RX)":                {},
};

/** Index of (componentType + key) → field, for server validation & detail-page labels. */
export function getFieldDef(componentTypeName: string | undefined | null, key: string): ParamField | undefined {
  const spec = getSpecForComponentType(componentTypeName);
  if (!spec) return undefined;
  if (spec.variant && spec.variant.key === key) {
    return { key, label: spec.variant.label, type: "select", options: spec.variant.options, group: VARIANT_PARAM_GROUP };
  }
  for (const f of spec.commonFields) if (f.key === key) return f;
  if (spec.variant) {
    for (const list of Object.values(spec.variant.fieldsByVariant)) {
      for (const f of list) if (f.key === key) return f;
    }
  }
  return undefined;
}
