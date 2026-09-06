"""Port of ../../../src/lib/components/parameterSpecs.ts — keep in sync line-by-line.

Canonical component-parameter dictionary. Single source of truth for the
structured, unit-labelled parameter fields that appear per component type.
Consumed here by systems POST/PATCH to validate/coerce values + stamp the
canonical unit.

Storage stays relational: every field below maps to one `component_parameters`
row keyed by its snake_case `key`.

`component_type` MUST match a `component_types.name` row.

Only the backend-consumed surface is ported: `COMPONENT_PARAM_SPECS`,
`get_spec_for_component_type`, and `get_field_def`. `fieldsForSpec()` and
`COMPONENT_TYPE_CONTEXT` in the TS source are UI-only (wizard field
rendering / component-type-chip filtering) — nothing under
src/app/api/qsecdb imports either, so they're out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ParamFieldType = Literal["number", "text", "select", "boolean"]

DEFAULT_PARAM_GROUP = "parameters"
VARIANT_PARAM_GROUP = "settings"
# "annotations" is a display-only bucket for free-form user notes.
# No pipeline process (applicability engine, simulation, import) may read or
# act on rows where param_group = 'annotations'.


@dataclass
class ParamField:
    key: str  # canonical snake_case key -> stored in component_parameters.key
    label: str  # human-readable label shown in the form
    type: ParamFieldType
    unit: str | None = None  # canonical unit -> stored in component_parameters.unit (None = unitless)
    options: list[str] | None = None  # allowed values for type "select"
    group: str | None = None  # param_group bucket (defaults to "parameters")
    description: str | None = None


@dataclass
class VariantSpec:
    key: str  # discriminator key, e.g. "detector_variant" (stored under group "settings")
    label: str
    options: list[str]
    fields_by_variant: dict[str, list[ParamField]]  # extra fields revealed for each variant option


@dataclass
class ComponentParamSpec:
    component_type: str  # must equal a component_types.name row
    common_fields: list[ParamField]  # shown for every variant
    variant: VariantSpec | None = None


# ─── Reusable field fragments ────────────────────────────────────────────────
_operating_wavelength = ParamField(
    key="operating_wavelength", label="Operating wavelength", unit="nm", type="number",
    description="Photon wavelength the component is designed for; typically 1310 nm or 1550 nm for telecom-band QKD. Must match the channel and detector sensitivity band.",
)
_insertion_loss = ParamField(
    key="insertion_loss", label="Insertion loss", unit="dB", type="number",
    description="Signal power lost passing through the component (dB). Excess loss reduces the photon flux reaching the detector and lowers the achievable key rate.",
)
_extinction_ratio = ParamField(
    key="extinction_ratio", label="Extinction ratio", unit="dB", type="number",
    description="Ratio of maximum to minimum transmitted intensity (dB). Low extinction increases QBER by allowing wrong-basis photons to partially transmit.",
)
# Shared by every free-running APD variant (and by "SD APD", which adds a gate
# frequency on top) — the quenching mode changes which attacks the applicability
# engine considers, not which parameters the detector exposes.
#
# A tuple, not a list: fields_by_variant hands each variant its own list built with
# `[*_FREE_RUNNING_APD_FIELDS]`, so an in-place edit to one variant's fields can't
# reach through a shared object and mutate the others'.
_FREE_RUNNING_APD_FIELDS: tuple[ParamField, ...] = (
    ParamField(key="afterpulse_probability", label="Afterpulse probability", type="number",
               description="Probability of a spurious count triggered by charge trapping from a previous detection (0-1). Contributes to QBER in high repetition-rate systems."),
    ParamField(key="operating_temperature", label="Operating temperature", unit="°C", type="number",
               description="Detector operating temperature. APDs typically require cooling to −30 °C or below to suppress dark counts."),
)

# ─── Specs, keyed by component_types.name ────────────────────────────────────
COMPONENT_PARAM_SPECS: dict[str, ComponentParamSpec] = {
    # TX optical source. In most QKD systems the "single-photon source" is an
    # attenuated laser source, so the user's source fields live here.
    "Laser Source": ComponentParamSpec(
        component_type="Laser Source",
        common_fields=[
            ParamField(key="optical_pulse_repetition_rate", label="Optical pulse repetition rate", unit="Hz", type="number",
                       description="Rate at which optical pulses are emitted; sets the raw symbol rate of the QKD link."),
            ParamField(key="mean_photon_number", label="Mean photon number", unit="photons/pulse", type="number",
                       description="Average photons per pulse after attenuation (typically 0.1-0.5). Must be well below 1 to approximate a single-photon source and bound photon-number-splitting attacks."),
            ParamField(key="source_power", label="Source power", unit="W", type="number",
                       description="Optical output power of the laser before attenuation."),
            ParamField(key="long_term_power_stability", label="Long-term power stability", unit="dB/hr", type="number",
                       description="Power drift rate over hours (dB/hr). Instability can cause undetected changes in mean photon number, undermining decoy-state security."),
            ParamField(key="short_term_power_stability", label="Short-term power stability", unit="dB", type="number",
                       description="Pulse-to-pulse power variation (dB). Affects QBER and the accuracy of decoy-state intensity estimation."),
            ParamField(key="source_emission_temporal_profile", label="Source emission temporal profile", type="text",
                       description="Shape of the optical pulse envelope — e.g. Gaussian, sech2, square. Determines inter-symbol interference and timing-jitter sensitivity."),
            ParamField(key="source_timing_jitter", label="Source timing jitter", unit="s", type="number",
                       description="Uncertainty in photon emission time. Limits the achievable timing resolution and the width of detector coincidence windows."),
            ParamField(key="center_wavelength", label="Center wavelength", unit="nm", type="number",
                       description="Peak emission wavelength. Must match the QKD channel passband and detector sensitivity range."),
            ParamField(key="spectral_linewidth", label="Spectral linewidth", unit="nm", type="number",
                       description="Width of the optical spectrum. Narrow linewidth reduces chromatic dispersion in fibre and improves out-of-band noise filtering."),
        ],
    ),

    "Phase Modulator": ComponentParamSpec(
        component_type="Phase Modulator",
        common_fields=[
            ParamField(key="half_wave_voltage_vpi", label="Half-wave voltage (Vπ)", unit="V", type="number",
                       description="Drive voltage required to produce a π phase shift. Lower Vπ allows lower-voltage electronics and reduces drive power requirements."),
            ParamField(key="modulation_bandwidth", label="Modulation bandwidth", unit="Hz", type="number",
                       description="Maximum frequency at which the modulator can encode phase. Must exceed the QKD pulse repetition rate."),
            _insertion_loss,
            _extinction_ratio,
        ],
    ),

    "Intensity Modulator": ComponentParamSpec(
        component_type="Intensity Modulator",
        common_fields=[
            _extinction_ratio,
            ParamField(key="modulation_bandwidth", label="Modulation bandwidth", unit="Hz", type="number",
                       description="Maximum frequency at which intensity can be switched. Must support both the pulse rate and the decoy-state switching speed."),
            _insertion_loss,
            ParamField(key="number_of_intensity_levels", label="Number of intensity levels", type="number",
                       description="Number of distinct output power levels used — e.g. 3 for signal + 2 decoy intensities. Determines the complexity of the decoy-state protocol."),
        ],
    ),

    "Attenuator": ComponentParamSpec(
        component_type="Attenuator",
        common_fields=[
            ParamField(key="attenuation", label="Attenuation", unit="dB", type="number",
                       description="Nominal attenuation applied to reduce the source output to the target mean photon number."),
            ParamField(key="max_attenuation", label="Max attenuation", unit="dB", type="number",
                       description="Maximum achievable attenuation. Must be sufficient to reach the target µ at the highest source power."),
            ParamField(key="attenuation_accuracy", label="Attenuation accuracy", unit="dB", type="number",
                       description="Uncertainty in actual vs. set attenuation (dB). Inaccuracy causes the mean photon number to deviate from its target, affecting PNS attack bounds."),
            _insertion_loss,
        ],
    ),

    "Optical Isolator": ComponentParamSpec(
        component_type="Optical Isolator",
        common_fields=[
            ParamField(key="isolation", label="Isolation", unit="dB", type="number",
                       description="Attenuation of backward-propagating light (dB). Values ≥ 30 dB are required to suppress Trojan-horse back-injection and detector-blinding reflections."),
            _insertion_loss,
            _operating_wavelength,
        ],
    ),

    # Shared passive optics.
    "Beam Splitter": ComponentParamSpec(
        component_type="Beam Splitter",
        common_fields=[
            ParamField(key="splitting_ratio", label="Splitting ratio", type="text",
                       description='Power split between output ports — e.g. "50:50" for a balanced splitter or "90:10" for a tap. Determines basis selection probability in passive-choice receivers.'),
            _insertion_loss,
            _operating_wavelength,
        ],
    ),

    "Polarisation Component": ComponentParamSpec(
        component_type="Polarisation Component",
        common_fields=[_extinction_ratio, _insertion_loss, _operating_wavelength],
    ),

    "Polarization Controller": ComponentParamSpec(
        component_type="Polarization Controller",
        common_fields=[
            _extinction_ratio,
            ParamField(key="response_time", label="Response time", unit="s", type="number",
                       description="Time to stabilise to a new polarisation state. Slow response causes QBER spikes during channel polarisation drift events."),
            _insertion_loss,
        ],
    ),

    "Half-Wave Plate": ComponentParamSpec(
        component_type="Half-Wave Plate",
        common_fields=[
            ParamField(key="retardance", label="Retardance", unit="waves", type="number",
                       description="Phase retardance between fast and slow axes in units of wavelengths — e.g. 0.5 for a half-wave plate. Determines the polarisation rotation applied."),
            _operating_wavelength,
            _insertion_loss,
        ],
    ),

    "Compensation Crystal": ComponentParamSpec(
        component_type="Compensation Crystal",
        common_fields=[
            ParamField(key="material", label="Material", type="text",
                       description="Birefringent crystal material — e.g. YVO4, calcite. Determines the birefringence magnitude and temperature sensitivity."),
            ParamField(key="crystal_length", label="Crystal length", unit="mm", type="number",
                       description="Physical length of the crystal (mm). Determines the magnitude of birefringence compensation applied to the photon pairs."),
            _operating_wavelength,
        ],
    ),

    "Faraday Mirror": ComponentParamSpec(
        component_type="Faraday Mirror",
        common_fields=[
            ParamField(key="faraday_rotation_deviation", label="Faraday rotation deviation", unit="deg", type="number",
                       description="Deviation from the ideal 45° single-pass rotation (90° round trip). Non-zero deviation leaves a residual polarisation dependence that a passive eavesdropper can exploit; alignment procedures aim to minimise this value."),
            ParamField(key="polarization_extinction_ratio", label="Polarisation extinction ratio", unit="dB", type="number",
                       description="Ratio of the desired to unwanted polarisation component after the round trip. Low extinction indicates residual mirror imperfections that couple polarisation information into the phase-encoded signal."),
            _insertion_loss,
            _operating_wavelength,
        ],
    ),

    # EB-QKD source components.
    "Entangled Photon Source": ComponentParamSpec(
        component_type="Entangled Photon Source",
        common_fields=[
            ParamField(key="output_wavelength", label="Output wavelength", unit="nm", type="number",
                       description="Wavelength of the entangled photon pairs emitted toward Alice and Bob."),
            ParamField(key="pump_wavelength", label="Pump wavelength", unit="nm", type="number",
                       description="Wavelength of the pump laser driving pair generation; typically half the output wavelength for degenerate SPDC."),
            ParamField(key="pair_generation_rate", label="Pair generation rate", unit="Mio pairs/s", type="number",
                       description="Number of entangled photon pairs generated per second; governs the raw coincidence rate."),
            ParamField(key="heralding_efficiency", label="Heralding efficiency", unit="%", type="number",
                       description="Fraction of pairs where detecting one photon heralds the presence of the partner (0-100%). Low values increase the multi-photon contribution and raise the QBER."),
            ParamField(key="entanglement_fidelity", label="Entanglement fidelity", unit="%", type="number",
                       description="Fidelity of the generated state to the ideal Bell state (0-100%). Low fidelity directly inflates QBER and can invalidate security proofs."),
            ParamField(key="spectral_bandwidth", label="Spectral bandwidth", unit="nm", type="number",
                       description="Bandwidth of the generated paired photons. Broader bandwidth increases pair rate but degrades spectral correlations and requires wider-bandwidth filtering."),
            ParamField(key="long_term_stability", label="Long-term stability", unit="dB/hr", type="number",
                       description="Drift of pair generation rate over hours. Instability can cause undetected changes in the quantum bit error rate."),
        ],
    ),

    "SPDC Nonlinear Crystal": ComponentParamSpec(
        component_type="SPDC Nonlinear Crystal",
        common_fields=[
            ParamField(key="material", label="Crystal material", type="text",
                       description="Nonlinear crystal material — e.g. PPKTP, BBO, PPLN, KTP. Determines conversion efficiency, phase-matching bandwidth, and thermal stability."),
            ParamField(key="phase_matching_type", label="Phase-matching type", type="select", options=["type-I", "type-II", "type-0"],
                       description="Geometry of the nonlinear interaction. Type-II produces polarisation-entangled pairs directly; type-0/I require additional polarisation optics."),
            ParamField(key="pump_wavelength", label="Pump wavelength", unit="nm", type="number",
                       description="Wavelength of the pump laser input to the crystal."),
            ParamField(key="signal_wavelength", label="Signal wavelength", unit="nm", type="number",
                       description="Wavelength of the signal output photon."),
            ParamField(key="idler_wavelength", label="Idler wavelength", unit="nm", type="number",
                       description="Wavelength of the idler output photon. Signal and idler photon energies sum to match the pump photon energy."),
            ParamField(key="poling_period", label="Poling period", unit="µm", type="number",
                       description="Quasi-phase-matching period (PPKTP / PPLN only). Determines the phase-matched wavelength at a given operating temperature."),
            ParamField(key="crystal_length", label="Crystal length", unit="mm", type="number",
                       description="Physical length of the crystal (mm). Longer crystals increase brightness but narrow the spectral bandwidth of the generated pairs."),
            ParamField(key="brightness", label="Brightness", unit="pairs/s/mW/nm", type="number",
                       description="Pair generation rate per unit pump power per unit bandwidth. Higher brightness enables higher key rates at lower pump powers."),
        ],
    ),

    # RX detectors.
    "Single-Photon Detector": ComponentParamSpec(
        component_type="Single-Photon Detector",
        common_fields=[
            ParamField(key="detection_efficiency", label="Detection efficiency", type="number",
                       description="Probability of registering a click given an incident photon (0-1). Higher efficiency increases key rate but typically increases dark counts and timing jitter."),
            ParamField(key="dark_count_rate", label="Dark count rate", unit="cps", type="number",
                       description="Rate of spurious detection events with no incident photon (counts/s). Contributes directly to QBER and limits the signal-to-noise ratio."),
            ParamField(key="dead_time", label="Dead time", unit="s", type="number",
                       description="Minimum interval between detectable events. Limits the maximum count rate and creates blind windows that time-shift attacks can exploit."),
            ParamField(key="timing_jitter", label="Timing jitter", unit="s", type="number",
                       description="Uncertainty in the registered photon arrival time. Limits achievable timing resolution and the usable coincidence window in time-bin protocols."),
            _operating_wavelength,
        ],
        variant=VariantSpec(
            key="detector_variant", label="Detector variant",
            # These strings are the keys of VARIANT_TO_DET_TYPE in app/qkd/applicability.py —
            # the applicability engine reads them to decide which detector-control attacks
            # apply. An APD has two independent axes: gating (gated vs free-running) and
            # quenching (actively vs passively quenched), and BSI catalogues an attack per
            # combination. Plain "APD (free-running)" leaves quenching unstated, which makes
            # the engine report BOTH quenching attacks; the explicit variants narrow that.
            options=[
                "APD (gated)",
                "APD (free-running)",
                "APD (free-running, actively quenched)",
                "APD (free-running, passively quenched)",
                "SD APD",
                "SNSPD",
                "TES",
            ],
            fields_by_variant={
                "APD (gated)": [
                    ParamField(key="gate_frequency", label="Gate frequency", unit="Hz", type="number",
                               description="Rate at which the APD is enabled. Must synchronise precisely with the QKD pulse train."),
                    ParamField(key="gate_width", label="Gate width", unit="s", type="number",
                               description="Duration of each detection window. Shorter gates reduce dark counts but require tighter timing synchronisation."),
                    ParamField(key="afterpulse_probability", label="Afterpulse probability", type="number",
                               description="Probability of a spurious count triggered by charge trapping from a previous detection (0-1). Contributes to QBER in high repetition-rate systems."),
                    ParamField(key="operating_temperature", label="Operating temperature", unit="°C", type="number",
                               description="Detector operating temperature. APDs typically require cooling to −30 °C or below to suppress dark counts."),
                ],
                "APD (free-running)": [*_FREE_RUNNING_APD_FIELDS],
                "APD (free-running, actively quenched)": [*_FREE_RUNNING_APD_FIELDS],
                "APD (free-running, passively quenched)": [*_FREE_RUNNING_APD_FIELDS],
                # Self-differencing APDs are free-running APDs read out through a
                # gate, so they carry the shared fields plus their own gate frequency
                # (whose description differs from the gated variant's).
                "SD APD": [
                    ParamField(key="gate_frequency", label="Gate frequency", unit="Hz", type="number",
                               description="Rate at which the APD is enabled. Self-differencing APDs are gated at GHz rates, with the previous gate's response subtracted to reveal the avalanche."),
                    *_FREE_RUNNING_APD_FIELDS,
                ],
                "TES": [
                    ParamField(key="operating_temperature", label="Operating temperature", unit="K", type="number",
                               description="Cryogenic operating temperature. Transition-edge sensors are biased within their superconducting transition, typically below 100 mK."),
                    ParamField(key="reset_time", label="Reset time", unit="s", type="number",
                               description="Thermal recovery time after a detection event before the sensor can register another photon. TES reset times are far longer than APD dead times."),
                ],
                "SNSPD": [
                    ParamField(key="operating_temperature", label="Operating temperature", unit="K", type="number",
                               description="Cryogenic operating temperature. SNSPDs typically operate at 0.8-4 K using a closed-cycle refrigerator."),
                    ParamField(key="reset_time", label="Reset time", unit="s", type="number",
                               description="Time after a detection event before the SNSPD can reliably detect again (nanowire recovery time)."),
                    ParamField(key="max_count_rate", label="Max count rate", unit="cps", type="number",
                               description="Maximum sustainable detection rate before dead-time losses become significant."),
                    ParamField(key="bias_current", label="Bias current", unit="µA", type="number",
                               description="DC current setting the operating point on the SNSPD switching curve. Determines the trade-off between efficiency and dark count rate."),
                ],
            },
        ),
    ),

    "Coherent Detector": ComponentParamSpec(
        component_type="Coherent Detector",
        common_fields=[
            ParamField(key="detection_scheme", label="Detection scheme", type="select", options=["homodyne", "heterodyne"], group=VARIANT_PARAM_GROUP,
                       description="Measurement basis — homodyne measures one quadrature (X or P); heterodyne measures both simultaneously at a 3 dB SNR penalty."),
            ParamField(key="quantum_efficiency", label="Quantum efficiency", type="number",
                       description="Photodiode conversion efficiency (0-1). Determines the shot-noise-limited SNR of the balanced detector."),
            ParamField(key="electronic_noise", label="Electronic noise", unit="shot-noise units", type="number",
                       description="Detector noise floor relative to shot noise. Values ≥ 1 indicate thermal noise dominates, which can compromise CV-QKD security proofs."),
            ParamField(key="detection_bandwidth", label="Detection bandwidth", unit="Hz", type="number",
                       description="RF bandwidth of the balanced detector. Must exceed the modulation bandwidth of the transmitted CV signal."),
            ParamField(key="clearance", label="Clearance", unit="dB", type="number",
                       description="Ratio of shot noise to electronic noise (dB). Typically ≥ 10 dB is required for secure CV-QKD key generation."),
            ParamField(key="local_oscillator_power", label="Local oscillator power", unit="mW", type="number",
                       description="Optical power of the LO beam. Higher LO power increases shot noise relative to electronic noise, improving clearance."),
        ],
    ),

    "Injected Light Monitor": ComponentParamSpec(
        component_type="Injected Light Monitor",
        common_fields=[
            ParamField(key="detection_threshold_power", label="Detection threshold power", unit="W", type="number",
                       description="Minimum optical power level that triggers an alarm. Should be set below the power level where injected light can influence detector behaviour."),
            ParamField(key="response_time", label="Response time", unit="s", type="number",
                       description="Time to respond to an injection event. Shorter response limits the duration window of a successful blinding attack."),
            _operating_wavelength,
        ],
    ),

    "Time-Digital Converter": ComponentParamSpec(
        component_type="Time-Digital Converter",
        common_fields=[
            ParamField(key="time_resolution", label="Time resolution", unit="s", type="number",
                       description="Smallest resolvable time interval (s). Determines timestamp precision and limits timing-jitter compensation capability."),
            ParamField(key="dead_time", label="Dead time", unit="s", type="number",
                       description="Minimum interval between consecutive registered events. Creates blind spots that time-shift attacks can exploit."),
            ParamField(key="number_of_channels", label="Number of channels", type="number",
                       description="Number of independent timing input channels. One channel per detector is required."),
        ],
    ),

    "Coincidence Matcher": ComponentParamSpec(
        component_type="Coincidence Matcher",
        common_fields=[
            ParamField(key="coincidence_window", label="Coincidence window", unit="s", type="number",
                       description="Maximum Alice-Bob detection time difference counted as a coincident pair (s). Must be wider than system timing jitter but narrow enough to reject accidental coincidences."),
            ParamField(key="number_of_channels", label="Number of channels", type="number",
                       description="Number of independent input channels. At least 2 are required for EB-QKD (one per Alice, one per Bob)."),
        ],
    ),

    # TX/RX control electronics.
    "FPGA / System Controller (TX)": ComponentParamSpec(
        component_type="FPGA / System Controller (TX)",
        common_fields=[
            ParamField(key="clock_frequency", label="System clock frequency", unit="Hz", type="number",
                       description="Master system clock rate (Hz). Must be stable and synchronised with the partner node clock for accurate time-tagging."),
            ParamField(key="firmware_version", label="Firmware version", type="text",
                       description="Semantic version identifier of the loaded firmware. Required for traceability and security patch management."),
            ParamField(key="configuration_interface", label="Configuration interface", type="select",
                       options=["JTAG", "SPI", "I2C", "Ethernet", "USB"],
                       description="Interface used to load or update firmware. Determines the attack surface for unauthorised firmware modification."),
            ParamField(key="logic_cells", label="Logic cells", type="number",
                       description="Total FPGA logic capacity (LUTs / ALMs). Determines the headroom available for additional processing or security modules."),
        ],
    ),

    "FPGA / System Controller (RX)": ComponentParamSpec(
        component_type="FPGA / System Controller (RX)",
        common_fields=[
            ParamField(key="clock_frequency", label="System clock frequency", unit="Hz", type="number",
                       description="Master system clock rate (Hz). Must be stable and synchronised with the partner node clock for accurate time-tagging."),
            ParamField(key="firmware_version", label="Firmware version", type="text",
                       description="Semantic version identifier of the loaded firmware. Required for traceability and security patch management."),
            ParamField(key="configuration_interface", label="Configuration interface", type="select",
                       options=["JTAG", "SPI", "I2C", "Ethernet", "USB"],
                       description="Interface used to load or update firmware. Determines the attack surface for unauthorised firmware modification."),
            ParamField(key="logic_cells", label="Logic cells", type="number",
                       description="Total FPGA logic capacity (LUTs / ALMs). Determines the headroom available for additional processing or security modules."),
        ],
    ),

    "Clock Synthesizer (TX)": ComponentParamSpec(
        component_type="Clock Synthesizer (TX)",
        common_fields=[
            ParamField(key="output_frequency", label="Output frequency", unit="Hz", type="number",
                       description="Clock frequency delivered to the QKD system. Must match the link pulse repetition rate."),
            ParamField(key="reference_frequency", label="Reference frequency", unit="Hz", type="number",
                       description="External reference input frequency (omit if free-running). Sets the disciplining source for the synthesiser PLL."),
            ParamField(key="timing_jitter", label="Timing jitter (RMS)", unit="s", type="number",
                       description="RMS timing uncertainty of the synthesised clock (s). Directly contributes to overall system timing jitter and the width of the coincidence window."),
            ParamField(key="phase_noise", label="Phase noise @ 10 kHz offset", unit="dBc/Hz", type="number",
                       description="Spectral purity at 10 kHz offset (dBc/Hz). High phase noise creates timing uncertainty that widens the coincidence window and increases accidental coincidences."),
            ParamField(key="synchronization_mode", label="Synchronization mode", type="select",
                       options=["internal", "external", "GPS-disciplined"],
                       description="How the clock is referenced — internal free-running, locked to an external reference, or GPS-disciplined for long-distance links."),
        ],
    ),

    "Clock Synthesizer (RX)": ComponentParamSpec(
        component_type="Clock Synthesizer (RX)",
        common_fields=[
            ParamField(key="output_frequency", label="Output frequency", unit="Hz", type="number",
                       description="Clock frequency delivered to the QKD system. Must match the link pulse repetition rate."),
            ParamField(key="reference_frequency", label="Reference frequency", unit="Hz", type="number",
                       description="External reference input frequency (omit if free-running). Sets the disciplining source for the synthesiser PLL."),
            ParamField(key="timing_jitter", label="Timing jitter (RMS)", unit="s", type="number",
                       description="RMS timing uncertainty of the synthesised clock (s). Directly contributes to overall system timing jitter and the width of the coincidence window."),
            ParamField(key="phase_noise", label="Phase noise @ 10 kHz offset", unit="dBc/Hz", type="number",
                       description="Spectral purity at 10 kHz offset (dBc/Hz). High phase noise creates timing uncertainty that widens the coincidence window and increases accidental coincidences."),
            ParamField(key="synchronization_mode", label="Synchronization mode", type="select",
                       options=["internal", "external", "GPS-disciplined"],
                       description="How the clock is referenced — internal free-running, locked to an external reference, or GPS-disciplined for long-distance links."),
        ],
    ),

    "RF Driver (TX)": ComponentParamSpec(
        component_type="RF Driver (TX)",
        common_fields=[
            ParamField(key="bandwidth", label="Bandwidth", unit="Hz", type="number",
                       description="Frequency range over which the driver delivers full output power. Must exceed the highest required modulation frequency."),
            ParamField(key="output_voltage_swing", label="Output voltage swing (Vpp)", unit="V", type="number",
                       description="Peak-to-peak voltage delivered to the modulator. Must meet or exceed the modulator's Vπ to achieve full extinction."),
            ParamField(key="rise_time", label="Rise time (10-90%)", unit="s", type="number",
                       description="10-90% transition time of the output pulse. Fast rise times sharply define modulation windows and reduce inter-symbol interference."),
            ParamField(key="gain", label="Gain", unit="dB", type="number",
                       description="Signal amplification (dB). Determines the drive level delivered to the modulator."),
        ],
    ),

    "RF Driver (RX)": ComponentParamSpec(
        component_type="RF Driver (RX)",
        common_fields=[
            ParamField(key="bandwidth", label="Bandwidth", unit="Hz", type="number",
                       description="Frequency range over which the driver delivers full output power. Must exceed the highest required modulation frequency."),
            ParamField(key="output_voltage_swing", label="Output voltage swing (Vpp)", unit="V", type="number",
                       description="Peak-to-peak voltage delivered to the modulator. Must meet or exceed the modulator's Vπ to achieve full extinction."),
            ParamField(key="rise_time", label="Rise time (10-90%)", unit="s", type="number",
                       description="10-90% transition time of the output pulse. Fast rise times sharply define modulation windows and reduce inter-symbol interference."),
            ParamField(key="gain", label="Gain", unit="dB", type="number",
                       description="Signal amplification (dB). Determines the drive level delivered to the modulator."),
        ],
    ),
}

# ─── Lookup (tolerant of case / surrounding whitespace) ──────────────────────
_NORMALIZED_INDEX: dict[str, ComponentParamSpec] = {}
for _spec in COMPONENT_PARAM_SPECS.values():
    _NORMALIZED_INDEX[_spec.component_type.strip().lower()] = _spec
# "Avalanche Photon Detector" is merged into Single-Photon Detector as APD variants.
# The component_type row is kept in the DB for vulnerability_applicability FK references,
# but the form no longer offers it as a standalone type.
_NORMALIZED_INDEX["avalanche photon detector"] = _NORMALIZED_INDEX["single-photon detector"]


def get_spec_for_component_type(name: str | None) -> ComponentParamSpec | None:
    if not name:
        return None
    return _NORMALIZED_INDEX.get(name.strip().lower())


def get_field_def(component_type_name: str | None, key: str) -> ParamField | None:
    """Index of (component_type + key) -> field, for server validation & detail-page labels."""
    spec = get_spec_for_component_type(component_type_name)
    if spec is None:
        return None
    if spec.variant and spec.variant.key == key:
        return ParamField(key=key, label=spec.variant.label, type="select", options=spec.variant.options, group=VARIANT_PARAM_GROUP)
    for f in spec.common_fields:
        if f.key == key:
            return f
    if spec.variant:
        for lst in spec.variant.fields_by_variant.values():
            for f in lst:
                if f.key == key:
                    return f
    return None
