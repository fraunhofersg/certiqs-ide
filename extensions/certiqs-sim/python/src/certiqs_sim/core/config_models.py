"""Component configuration dataclasses for the quantum-channel twin.

These are the *live, mutable* runtime configs the twin operates on (the tunable
sliders mutate them in place between windows).  They are intentionally plain
dataclasses — the typed, validated YAML manifest models live in
``certiqs_sim.config.manifest_models`` and are converted into these at build time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from certiqs_sim.core.linalg import DEFAULT_COHERENCE_TIME_PS, FIBER_GROUP_INDEX


@dataclass
class SourceConfig:
    bell_state: str = "phi_plus"
    pair_generation_probability_per_pulse: float = 0.01
    intrinsic_visibility: float = 0.97
    repetition_rate_hz: float = 100e6
    generated_wavelength_nm: float = 1550.0
    multi_pair_model: str = "poisson"


@dataclass
class LinkBudgetAgeing:
    """Fibre / joint ageing contribution to the QKD link budget.

    ``excess_loss_db`` is the realised (current) excess.  ``rate_db_per_year``
    and ``service_life_years`` seed later time-evolution / remaining-life models.
    """

    enabled: bool = False
    excess_loss_db: float = 0.0
    rate_db_per_year: float = 0.0
    service_life_years: float = 0.0


@dataclass
class LinkBudgetContamination:
    """Contamination (connector end-face dirt, residues) excess loss."""

    enabled: bool = False
    excess_loss_db: float = 0.0
    #: Probability that a given connector face is contaminated (future stochastic model).
    connector_contamination_prob: float = 0.0


@dataclass
class LinkBudgetBending:
    """Macrobending excess loss and installed-bend geometry hints."""

    enabled: bool = False
    excess_loss_db: float = 0.0
    min_bend_radius_mm: float = 30.0
    induced_loss_db_per_turn: float = 0.1
    num_tight_bends: int = 0


@dataclass
class LinkBudgetMeasurementUncertainty:
    """1σ measurement / characterisation uncertainties for later Monte Carlo budgets.

    These do **not** alter the mean transmission; they parameterise uncertainty
    bands and sampled link budgets.
    """

    attenuation_db_per_km_sigma: float = 0.0
    length_km_sigma: float = 0.0
    splice_loss_db_sigma: float = 0.0
    connector_loss_db_sigma: float = 0.0
    #: Confidence level for planning bands (e.g. 0.95 → ~2σ when Gaussian).
    loss_budget_confidence: float = 0.95


@dataclass
class LinkBudgetConfig:
    """QKD optical link budget margins and impairment reservoirs.

    Installed geometry (length, splices, connectors, attenuation) remains on
    :class:`FiberConfig`.  This block carries design margin plus ageing /
    contamination / bending / measurement-uncertainty parameters for later
    simulation and field-life modelling.
    """

    #: Planning reserve (dB). Not applied to mean η unless
    #: ``apply_design_margin`` is true.
    design_margin_db: float = 0.0
    apply_design_margin: bool = False
    ageing: LinkBudgetAgeing = field(default_factory=LinkBudgetAgeing)
    contamination: LinkBudgetContamination = field(
        default_factory=LinkBudgetContamination
    )
    bending: LinkBudgetBending = field(default_factory=LinkBudgetBending)
    measurement_uncertainty: LinkBudgetMeasurementUncertainty = field(
        default_factory=LinkBudgetMeasurementUncertainty
    )

    def ageing_excess_db(self) -> float:
        if not self.ageing.enabled:
            return 0.0
        # Prefer explicit excess; else derive a simple linear life model.
        excess = max(float(self.ageing.excess_loss_db), 0.0)
        if excess > 0.0:
            return excess
        return max(
            float(self.ageing.rate_db_per_year)
            * max(float(self.ageing.service_life_years), 0.0),
            0.0,
        )

    def contamination_excess_db(self) -> float:
        if not self.contamination.enabled:
            return 0.0
        return max(float(self.contamination.excess_loss_db), 0.0)

    def bending_excess_db(self) -> float:
        if not self.bending.enabled:
            return 0.0
        turns = max(int(self.bending.num_tight_bends), 0)
        return max(float(self.bending.excess_loss_db), 0.0) + turns * max(
            float(self.bending.induced_loss_db_per_turn), 0.0
        )

    def design_margin_applied_db(self) -> float:
        if not self.apply_design_margin:
            return 0.0
        return max(float(self.design_margin_db), 0.0)

    def excess_loss_db(self) -> float:
        """Sum of budget impairments currently folded into mean channel loss."""
        return (
            self.ageing_excess_db()
            + self.contamination_excess_db()
            + self.bending_excess_db()
            + self.design_margin_applied_db()
        )


@dataclass
class FiberConfig:
    length_km: float = 0.0
    attenuation_db_per_km: float = 0.2
    # Design wavelength for the fibre model (nm); documents ITU window / loss context.
    wavelength_nm: float = 1550.0
    # Discrete joint losses (connectors, fusion splices).
    num_splices: int = 0
    splice_loss_db: float = 0.05  # per splice
    num_connectors: int = 0
    connector_loss_db: float = 0.25  # per connector
    # Additional fixed insertion / margin (legacy lump totals fold in here).
    insertion_loss_db: float = 0.0
    depolarization_prob: float = 0.0
    # Residual decoherence that accumulates with length (Pauli dep. intensity / km).
    # Keeps length sweeps physically meaningful when dark counts ≪ signal.
    depolarization_per_km: float = 0.002
    pmd_ps: float = 0.0
    background_photon_rate_hz: float = 0.0
    coupling_efficiency: float = 1.0
    static_rotation_rad: float = 0.0
    drift_sigma_rad: float = 0.0
    fiber_group_index: float = FIBER_GROUP_INDEX
    coherence_time_ps: float = DEFAULT_COHERENCE_TIME_PS
    link_budget: LinkBudgetConfig = field(default_factory=LinkBudgetConfig)

    def discrete_loss_db(self) -> float:
        """Connector + splice + fixed insertion losses (dB)."""
        return (
            max(int(self.num_splices), 0) * max(float(self.splice_loss_db), 0.0)
            + max(int(self.num_connectors), 0) * max(float(self.connector_loss_db), 0.0)
            + max(float(self.insertion_loss_db), 0.0)
        )

    def fibre_propagation_loss_db(self) -> float:
        return max(float(self.length_km), 0.0) * max(float(self.attenuation_db_per_km), 0.0)

    def link_budget_excess_db(self) -> float:
        return self.link_budget.excess_loss_db()

    def total_loss_db(self) -> float:
        return (
            self.fibre_propagation_loss_db()
            + self.discrete_loss_db()
            + self.link_budget_excess_db()
        )


@dataclass
class DetectorSpec:
    label: str
    basis: str
    bit: int
    channel_id: int
    efficiency: float
    dark_count_hz: float
    jitter_ps_rms: float
    dead_time_ns: float
    afterpulse_prob: float


@dataclass
class LedSaltConfig:
    """Self-test LED operated in *salt* mode.

    The light emitter of the detector self-testing scheme is fired at private,
    random times.  ``on_probability`` is the per-round probability that it fires;
    ``mean_photon_number`` is the total mean photon number n̄ of that pulse.

    The LED is unpolarised, so the mean photon number splits evenly across the
    two polarisation modes — this is what the rx-povm service consumes as a
    thermal ``LedState`` with per-mode means ``n_h`` / ``n_v``.
    """

    enabled: bool = False
    mean_photon_number: float = 0.0
    on_probability: float = 0.0

    def per_mode_means(self) -> tuple[float, float]:
        """(n_h, n_v) for an unpolarised thermal emitter."""
        half = max(float(self.mean_photon_number), 0.0) / 2.0
        return half, half

    def fires_this_round(self, rng: Any) -> bool:
        if not self.enabled:
            return False
        return rng.random() < min(max(float(self.on_probability), 0.0), 1.0)


@dataclass
class ReceiverConfig:
    name: str
    input_coupler_loss_db: float
    basis_bs_ratio_z: float
    basis_bs_ratio_x: float
    basis_bs_insertion_loss_db: float
    z_pbs_loss_db: float
    x_pbs_loss_db: float
    eps_z: float
    eps_x: float
    angle_deg_x_hwp: float
    angle_error_deg_sigma: float
    detectors: dict[str, DetectorSpec] = field(default_factory=dict)
    led: LedSaltConfig = field(default_factory=LedSaltConfig)

    @property
    def basis_bs_bias(self) -> float:
        """Fraction of light routed to the Z arm, i.e. the basis-choice BS bias.

        0.5 is an unbiased 50/50 splitter; 1.0 sends everything to Z.
        """
        total = float(self.basis_bs_ratio_z) + float(self.basis_bs_ratio_x)
        if total <= 1e-12:
            return 0.5
        return float(self.basis_bs_ratio_z) / total

    def set_basis_bs_bias(self, bias: float) -> None:
        """Set the Z/X split from a single bias scalar, preserving normalisation."""
        b = min(max(float(bias), 0.0), 1.0)
        self.basis_bs_ratio_z = b
        self.basis_bs_ratio_x = 1.0 - b


@dataclass
class TimingConfig:
    coincidence_window_ps: float
    time_sync_jitter_ps_rms: float


__all__ = [
    "DetectorSpec",
    "FiberConfig",
    "LedSaltConfig",
    "LinkBudgetAgeing",
    "LinkBudgetBending",
    "LinkBudgetConfig",
    "LinkBudgetContamination",
    "LinkBudgetMeasurementUncertainty",
    "ReceiverConfig",
    "SourceConfig",
    "TimingConfig",
]
