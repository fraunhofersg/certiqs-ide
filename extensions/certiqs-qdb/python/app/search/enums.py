"""Static option lists used by field_registry.py's FieldOptions.

Ports of src/lib/qkd/attackEnums.ts, systemEnums.ts, countermeasureEnums.ts,
eaParameterEnums.ts — values only (the validation helper functions in those
files belong to the CRUD routes that use them, ported in a later phase).
"""

MODULES = ("Transmitter", "Receiver", "Post-processing")

ATTACK_TYPES = ("Active", "Passive", "Mixed")

FEASIBILITY_OPTIONS = (
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
)

EXPERTISE_OPTIONS = ("Laymen", "Proficient", "Expert", "Multiple experts")

OPPORTUNITY_OPTIONS = ("Unlimited", "Easy", "Moderate", "Difficult")

EQUIPMENT_OPTIONS = ("Standard", "Specialised", "Bespoke", "Multiple Bespoke", "Non-existent")

ATTACK_RATINGS = ("Basic", "Enhanced Basic", "Moderate", "High", "Beyond High", "Vulnerability")

DOUBLE_CLICK_HANDLING = ("discard", "randomAssign", "securityProofAware")

BASIS_CHOICE = ("active", "passive", "mixed")

DEPLOYMENT = ("ground-fiber", "ground-free-space", "satellite", "lab-demo")

OPTICAL_PATH_DIRECTION = ("unidirectional", "bidirectional")

LOCAL_OSCILLATOR_TYPE = ("transmitted", "local")

PHASE_RANDOMISATION_METHOD = ("gain-switched", "external-modulator", "none")

RECONCILIATION_ALGORITHM = ("LDPC", "Cascade", "other")

COUNTERMEASURE_TYPES = ("Hardware", "Software", "Hardware + Software")

DEFENSE_EFFECTIVENESS = ("Proven Mitigation", "Robust", "Partial", "Untested")

PARAMETER_TYPES = (
    "Setup Range",
    "Setup Scalar",
    "Step Parameter",
    "Physical Constant",
    "Execution Parameter",
    "Measured Result",
)
