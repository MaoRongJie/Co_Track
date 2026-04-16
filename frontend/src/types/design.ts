export type ProductCategory =
  | 'high_speed_train'
  | 'intercity_train'
  | 'metro_vehicle'
  | 'automobile'
  | 'home_appliance'
  | 'industrial_other';

export type BaseModelSource = 'upload' | 'library' | 'generate';

export type PrecisionLevel = 'authoritative' | 'standard' | 'approximate';

export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW';

export type CanvasTool =
  | 'select'
  | 'pencil'
  | 'rect'
  | 'ellipse'
  | 'line'
  | 'eraser';

export interface DesignBrief {
  theme?: string;
  mainColors?: string[];
  accentColors?: string[];
  styleKeywords?: string[];
  designElements?: string[];
  constraintsHint?: string;
  productCategory: ProductCategory;
}

export type ProductProfileValue = string | number | boolean;
export type ProductProfile = Record<string, ProductProfileValue>;

export interface BaseModelInspectionMeta {
  fileName?: string;
  format?: string;
  meshCount?: number;
  materialCount?: number;
  bboxM?: number[];
  hasOriginalUv?: boolean;
  uvSource?: 'embedded' | 'auto_unwrapped' | string;
  uvTemplateMode?: string;
  warnings?: string[];
}

export interface BaseModelUvSpec {
  width?: number;
  height?: number;
  paintableUvPixels?: number;
}

export interface BaseModelMappingMeta {
  inspection?: BaseModelInspectionMeta;
  uvSpec?: BaseModelUvSpec;
  meshToRegion?: Record<string, string>;
}

export interface BaseModelMeta {
  baseModelId: number;
  sourceType: BaseModelSource;
  precisionLevel: PrecisionLevel;
  modelUrl: string;
  uvTemplateUrl: string;
  surfaceAreaM2: number;
  paintableUvPixels: number;
  exportGlbAllowed: boolean;
  licenseScope: 'self_owned' | 'internal' | 'external_restricted';
  lockedAt?: string;
  mappingMeta?: BaseModelMappingMeta;
}

export interface UvFocusPoint {
  u: number;
  v: number;
  source: 'uv' | 'model';
  token: number;
}

export interface BriefKeywordSnapshot {
  theme: string;
  main_colors: string[];
  accent_colors: string[];
  style_keywords: string[];
  design_elements: string[];
  constraints_hint: string;
}

export interface TexturePlanState {
  sessionId: number;
  sourceText: string;
  documentName: string | null;
  documentExcerpt: string;
  imageName: string | null;
  imageContentKeywords: string[];
  imageStyleKeywords: string[];
  selectedImageKeywords: string[];
  briefKeywords: BriefKeywordSnapshot;
  updatedAt: string;
}

export interface EngineeringResult {
  paintKg: number;
  materialCostYuan: number;
  laborHours: number;
  totalCostYuan: number;
  difficultyScore: number;
  confidenceLevel: ConfidenceLevel;
  confidenceReason: string;
}

export interface DesignScheme {
  id: string;
  name: string;
  author: string;
  mainColor: string;
  accentColor: string;
  clusterLabel: string;
  voteScore: number;
  version: number;
  engineering: EngineeringResult;
}

export interface TexturedModel {
  schemeId: string;
  title: string;
  promptText: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  texturedModelUrl: string | null;
  textureMaps: {
    baseColor: string | null;
    metallic: string | null;
    normal: string | null;
    roughness: string | null;
  } | null;
  editedVariant: {
    modelUrl: string;
    baseColorUrl: string;
    appliedAt: string;
  } | null;
  meshyTaskId: string | null;
  errorMessage: string | null;
}

export interface TextureModelsState {
  sessionId: number;
  status: 'idle' | 'queued' | 'processing' | 'completed' | 'failed';
  models: TexturedModel[];
  updatedAt: string;
}

export type RecommendationLevel =
  | 'highly_recommended'
  | 'recommended'
  | 'acceptable'
  | 'not_recommended';

/** Passenger-facing assessment for Stage 3 review. */
export interface PassengerAssessment {
  rideComfort: number;
  platformRecognition: number;
  socialAppeal: number;
  culturalFit: number;
  firstImpression: number;
}

/** Engineering assessment for Stage 3 review. */
export interface EngineeringAssessment {
  paintVolumeKg: number;
  colorZoneCount: number;
  maskingSteps: number;
  gradientRatioPercent: number;
  laborHours: number;
  processSteps: number;
  curveConformanceScore: number;
  materialCostYuan: number;
  laborCostYuan: number;
  totalCostYuan: number;
  colorVarianceRisk: ConfidenceLevel;
  weatherDurability: 'A' | 'B' | 'C';
  maintenanceCycleYears: number;
}

export type ReviewEngineeringAssessment = EngineeringAssessment;

/** Stage 3 review candidate derived from textured models. */
export interface ReviewScheme {
  id: string;
  name: string;
  author: string;
  schemeId: string;
  texturedModelUrl: string | null;
  baseColorTextureUrl: string | null;
  editedVariant: TexturedModel['editedVariant'] | null;
  engineering: EngineeringAssessment;
  passenger: PassengerAssessment;
  recommendation: RecommendationLevel;
  starredBy: string[];
}
