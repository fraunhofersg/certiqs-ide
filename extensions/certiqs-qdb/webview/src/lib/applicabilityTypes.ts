export type SystemOption = { id: number; name: string; manufacturer: string | null };

export type FeaturesUsed = {
  doubleClickHandling: string | null;
  basisChoice: string | null;
  detectorTypes: string[] | null;
  deployment: string | null;
  detectorAcceptsClicksOutsideGate: boolean | null;
  opticalPathDirection: string | null;
  sourceType: string | null;
  localOscillatorType: string | null;
  phaseRandomisationMethod: string | null;
  reconciliationAlgorithm: string | null;
  hasIntensityMonitor: boolean | null;
  hasDecoyCountermeasure?: boolean | null;
};

export type Countermeasure = {
  countermeasureId: number;
  name: string;
  description: string | null;
  defenseEffectiveness: string[] | null;
};

export type SystemCountermeasureRow = {
  countermeasure_id: number;
  module_id: number;
  module_type_id: number;
  module_type_name: string;
  name: string;
  description: string | null;
  countermeasure_type: string;
  cm_modules: string | null;
  component_type_ids: number[] | null;
};

// Input shape for creating/editing system countermeasures
export type SystemCmInput = { countermeasureId: number; moduleIndex: number };

export type Applicable = {
  vulnerabilityId: number;
  name: string;
  shortDescription: string | null;
  category: string | null;
  module: string | null;
  component: string | null;
  attackRating: string | null;
  matchedProtocols: string[];
  matchedComponents: string[];
  matchedConditions: string[];
  countermeasures: Countermeasure[];
  implementedCountermeasures: Countermeasure[];
};

export type Unevaluated = { vulnerabilityId: number; name: string; missing: string[] };

export type CrossFamilyUnknown = {
  vulnerabilityId: number;
  name: string;
  shortDescription: string | null;
  category: string | null;
  attackRating: string | null;
  module: string | null;
  matchedProtocols: string[];
  matchedComponents: string[];
  countermeasures: Countermeasure[];
};

export type ExcludedAttack = {
  vulnerabilityId: number;
  name: string;
  attackRating: string | null;
  reason: string;
};

export type NoScopeMatch = {
  vulnerabilityId: number;
  name: string;
  shortDescription: string | null;
  attackRating: string | null;
  module: string | null;
  component: string | null;
};

export type ConditionFailed = {
  vulnerabilityId: number;
  name: string;
  attackRating: string | null;
  reason: string;
  failedPath: string;
};

export type EAEquipment = {
  id: number;
  name: string;
  category: string | null;
  requiredFor: string | null;
};

export type ApplicableEA = {
  code: string;
  name: string;
  description: string | null;
  subclause: string | null;
  referencedFrom: string | null;
  score: number;
  equipment: EAEquipment[];
  applicableAttacks: {
    vulnerabilityId: number;
    name: string;
    attackRating: string | null;
    rationale: string | null;
  }[];
};

export type ApiResponse = {
  systemId: number;
  system: { id: number; name: string; manufacturer: string | null };
  featuresUsed: FeaturesUsed;
  systemComponentTypeNames: string[];
  systemCountermeasures: SystemCountermeasureRow[];
  applicable: Applicable[];
  unevaluated: Unevaluated[];
  crossFamilyUnknown: CrossFamilyUnknown[];
  excluded: ExcludedAttack[];
  noScopeMatch: NoScopeMatch[];
  conditionsFailed: ConditionFailed[];
};

export type Overrides = Partial<{
  doubleClickHandling: string;
  basisChoice: string;
  deployment: string;
  detectorAcceptsClicksOutsideGate: boolean;
  opticalPathDirection: string;
  sourceType: string;
  localOscillatorType: string;
  phaseRandomisationMethod: string;
  reconciliationAlgorithm: string;
}>;
