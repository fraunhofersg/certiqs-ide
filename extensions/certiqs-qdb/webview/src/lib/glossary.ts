export const EA_GLOSSARY: Record<string, string> = {
  "Pass Criteria":
    "Observable evidence or measurable outcome that constitutes a conformant result. If all pass criteria are met, the activity is marked as satisfied.",
  "Fail Criteria":
    "Conditions or observations that constitute a non-conformant result. Any fail criterion triggers a finding against the TOE.",
  "Dependencies":
    "Prerequisite evaluation activities or system conditions that must be satisfied or verified before this activity can be meaningfully assessed.",
  "threshold_average_overlap":
    "The overlap between the main sifted data from the RX and TX moduels corresponds to an agreement between the quantim states, when calculated for the accumulated data from execution_times sets of data.",
  "threshold_postprocessing":
    "The required minimum probability that the post-processing outputs or responses of the QKD module under test and the emulator are identical.",
  "threshold_g_k":
    "The absolute value of the difference between the measured value and the theoretical value of the k-th order correlation function, for a fixed intensity of the pulses emitted by the TX module",
  "threshold_mpn_min_k":
    "The minimum acceptable mean photon number (may be zero). Exists for each intensity k that the TX module emits under a protocol.",
  "threshold_mpn_max_k":
    "The maximum acceptable mean photon number (may be zero). Exists for each intensity k that the TX module emits under a protocol.",
  "threshold_int_corr_max":
    "Maximum difference between the average intensities of optical pulses prepared with the same intensity setting that were preceded by optical pulses prepared with different intensity settings.",
  "threshold_state_fidelity_min":
    "The minimum tolerable fidelity between the density matrix of the encoded quantum state and the ideal encoded state is required by the implemented QKD protocol.",
  "threshold_diff_ temp":
    "The maximum absolute difference in time of arrival between the states encoded by the TX module.",
  "threshold_diff_spec":
    "The maximum absolute difference in spectrum between the states encoded by the TX module.",
  "threshold_diff_theta":
    "The maximum absolute difference in the azimuthal angle of the polarisation ellipse between the states encoded by the TX module.",
  "threshold_diff_epsilon":
    "The maximum absolute difference in the ellipticitybetween the states encoded by the TX module.",
  "threshold_iso_transmitter":
    "The minimum isolation required for the isolation conmponent under test in the TX module.",
  "threshold_TX_monitor_cw":
    "The threshold power at which the injected light monitor indicates an exception event when bright continuous-wave emission is injected into the TX module under test.",
  "threshold_TX_monitor_pulse":
    "The threshold power at which the injected light monitor indicates an exception event when bright pulsed light is injected into the TX module under test.",
  "threshold_power_inc":
    "Maximum tolerable pulse intensity deviation caused by laser injection.",
  "threshold_spec_shift":
    "Maximum tolerable pulse spectrum deviation caused by laser injection.",
  "threshold_ph_change":
    "Maximum tolerable pulse phase deviation caused by laser injection.",
  "threshold_mismatch":
    "The maximum tolerable misamtch between the detetction probability responses in wavelength and time for the RX module under test that are required to be matched.",
  "threshold_RX_pbf":
    "The maximum probability that a back-flash photon exits from the RX module under test when a detection event occurs.",
  "threshold_iso_receiver":
    "The minimum isolation required for the isolation component under test in the RX module.",
  "threshold_RX_monitor_exp":
    "The power threshold at which the injected light monitor is designed to indicate an exception event when bright light is injected into the RX module under test.",
  "threshold_energy":
    "The threshold of trigger pulse's energy under detection blinding attack.",
  "threshold_dev_start_time":
    "The maximum deviation of the start time of a detector gate window when measured with optical signals at a single-photon level and at higher average intensity levels.",
  "threshold_dev_end_time":
    "The maximum deviation of the end time of a detector gate window when measured with optical signals at a single-photon level and at higher average intensity levels.",
  "threshold_lj_mismatch":
    "The maximum tolerable mismatch between the detection probability responses to the laser injection for the RX module under test that are required to be matched.",
  "threshold_basis_bias":
    "The maximum basis bias inn the raw data that can be tolerated.",
  "threshold_bit_bias":
    "The maximum bit bias in the raw data that can be tolerated.",
  "threshold_deviation":
    "The maximum tolerable deviation between the measured shot noise value and the shot noise value adopted in the implementation of the post-processing procedure of the TOE.",
};

export const GLOSSARY: Record<string, string> = {
  // Countermeasure scope
  "General":
    "Applies broadly across all QKD implementations regardless of attack type, architecture, or protocol.",
  "Specific":
    "Targets a defined attack vector or vulnerability class — effectiveness is scoped to that particular threat.",

  // Attack severity ratings (BSI)
  "High":
    "Attack poses significant risk. Exploitation is feasible with moderate expertise and produces high impact on key material security.",
  "Beyond High":
    "Severe risk. Exploitation is likely and could completely compromise QKD-generated key material.",
  "Moderate":
    "Moderate risk. Exploitation requires specific conditions, physical access, or elevated attacker expertise.",
  "Basic":
    "Minimal risk under normal operating conditions. May become relevant under highly constrained deployment scenarios.",
  "Enhanced Basic":
    "Low risk, one tier above Basic. Exploitation requires highly specific or rare conditions. Enhanced baseline controls beyond standard BSI Grundschutz are recommended, but full standard-level countermeasures are not required.",
  "Vulnerability":
    "A design-level protocol weakness rather than an active attack scenario. No specific exploitation rating assigned; the flaw exists structurally and requires architectural or specification-level mitigation.",

  // Defense effectiveness ratings (QIIA)
  "Proven Mitigation":
    "Rigorously integrated into the formal security proof, OR the security risk is mathematically non-existent with this countermeasure in place. (QIIA: C3)",
  "Robust":
    "Experimentally proven to effectively resist the specific attack strategy, but not yet formally incorporated into a security proof. (QIIA: C2)",
  "Partial":
    "Only effective against specific attack strategies; fails against alternative attacks or modified variants. (QIIA: C1)",
  "Insecure":
    "Has been shown to be insecure — a specific attack circumventing this countermeasure has been demonstrated. (QIIA: C0)",
  "Untested":
    "Suspected to mitigate the attack, but no testing or experimental verification has been conducted. (QIIA: CX)",
  "Unknown":
    "Insufficient data in BSI or QIIA documents to assign an effectiveness rating.",

  // Equipment availability
  "Non-existent equipment":
    "Requires tech not yet available (e.g. quantum memory)",
  "Bespoke equipment":
    "Custom-built hardware/software required",
  "Specialised equipment":
    "Lab/research-grade equipment needed",
  "Standard equipment":
    "Commercially off-the-shelf equipment sufficient",
};
