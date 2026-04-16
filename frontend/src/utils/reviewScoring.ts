import type {
  BaseModelMeta,
  ConfidenceLevel,
  EngineeringAssessment,
  PassengerAssessment,
  RecommendationLevel,
  ReviewScheme,
  TexturedModel,
} from '../types/design.ts';

const hashString = (input: string): number => {
  let hash = 5381;
  for (let index = 0; index < input.length; index += 1) {
    hash = ((hash << 5) + hash + input.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
};

const seededValue = (seed: string, min: number, max: number): number => {
  const hash = hashString(seed);
  return min + (hash % (Math.floor(max - min) + 1));
};

const seededFloat = (seed: string, min: number, max: number): number => {
  const hash = hashString(seed);
  const fraction = (hash % 1000) / 1000;
  return Math.round((min + fraction * (max - min)) * 10) / 10;
};

export const generateMockEngineeringAssessment = (
  model: TexturedModel,
  baseModel: BaseModelMeta | null,
): EngineeringAssessment => {
  const key = `${model.schemeId}:${model.meshyTaskId ?? 'no-meshy'}`;
  const surfaceArea = baseModel?.surfaceAreaM2 ?? 312;

  const colorZoneCount = seededValue(`${key}:zones`, 2, 7);
  const maskingSteps = Math.max(1, colorZoneCount - 1);
  const gradientRatioPercent = seededFloat(`${key}:gradient`, 5, 45);
  const paintVolumeKg =
    Math.round(
      surfaceArea * 0.38 * (1 + colorZoneCount * 0.04 + gradientRatioPercent * 0.003) * 10,
    ) / 10;

  const processSteps = seededValue(`${key}:steps`, 4, 8);
  const laborHours = seededValue(`${key}:labor`, 140, 260);
  const curveConformanceScore = seededValue(`${key}:curve`, 50, 95);

  const materialCostYuan = Math.round(paintVolumeKg * 310 + colorZoneCount * 1200);
  const laborCostYuan = Math.round(laborHours * 165);
  const totalCostYuan = materialCostYuan + laborCostYuan;

  const riskSeed = seededValue(`${key}:risk`, 0, 9);
  const colorVarianceRisk: ConfidenceLevel =
    gradientRatioPercent > 30 || colorZoneCount > 5
      ? 'HIGH'
      : riskSeed < 4
        ? 'LOW'
        : 'MEDIUM';

  const durabilitySeed = seededValue(`${key}:durability`, 0, 9);
  const weatherDurability: 'A' | 'B' | 'C' =
    durabilitySeed < 4 ? 'A' : durabilitySeed < 7 ? 'B' : 'C';

  return {
    paintVolumeKg,
    colorZoneCount,
    maskingSteps,
    gradientRatioPercent,
    laborHours,
    processSteps,
    curveConformanceScore,
    materialCostYuan,
    laborCostYuan,
    totalCostYuan,
    colorVarianceRisk,
    weatherDurability,
    maintenanceCycleYears: seededValue(`${key}:maintenance`, 3, 8),
  };
};

export const generateMockPassengerAssessment = (model: TexturedModel): PassengerAssessment => {
  const key = `${model.schemeId}:${model.meshyTaskId ?? 'no-meshy'}:passenger`;

  return {
    rideComfort: seededValue(`${key}:comfort`, 55, 95),
    platformRecognition: seededValue(`${key}:recognition`, 50, 92),
    socialAppeal: seededValue(`${key}:appeal`, 48, 96),
    culturalFit: seededValue(`${key}:culture`, 55, 90),
    firstImpression: seededValue(`${key}:impression`, 52, 95),
  };
};

export const computeRecommendation = (
  engineering: EngineeringAssessment,
  passenger: PassengerAssessment,
): RecommendationLevel => {
  const passengerValues = [
    passenger.rideComfort,
    passenger.platformRecognition,
    passenger.socialAppeal,
    passenger.culturalFit,
    passenger.firstImpression,
  ];
  const passengerAverage =
    passengerValues.reduce((sum, value) => sum + value, 0) / passengerValues.length;
  const allPassengerAbove70 = passengerValues.every((value) => value >= 70);

  const engineeringLooksSafe =
    engineering.colorZoneCount <= 4 &&
    engineering.gradientRatioPercent <= 25 &&
    engineering.curveConformanceScore >= 65;

  if (engineering.colorVarianceRisk === 'HIGH' && engineering.totalCostYuan > 100000) {
    return 'not_recommended';
  }

  if (engineeringLooksSafe && allPassengerAbove70 && passengerAverage >= 78) {
    return 'highly_recommended';
  }

  if (passengerAverage >= 65 && engineering.colorVarianceRisk !== 'HIGH') {
    return 'recommended';
  }

  return 'acceptable';
};

const FALLBACK_SCHEME_NAMES = [
  'Ice Stream',
  'Snow Gradient',
  'Fusion Pattern',
  'Azure Wave',
  'Crystal Line',
  'Northern Light',
];

export const buildReviewSchemes = (
  texturedModels: TexturedModel[],
  baseModel: BaseModelMeta | null,
): ReviewScheme[] => {
  const completedModels = texturedModels.filter((model) => model.status === 'completed');

  return completedModels.map((model, index) => {
    const engineering = generateMockEngineeringAssessment(model, baseModel);
    const passenger = generateMockPassengerAssessment(model);
    const recommendation = computeRecommendation(engineering, passenger);

    return {
      id: `review_${model.schemeId}`,
      name: model.title || FALLBACK_SCHEME_NAMES[index % FALLBACK_SCHEME_NAMES.length] || `Scheme ${index + 1}`,
      author: 'Current User',
      schemeId: model.schemeId,
      texturedModelUrl: model.editedVariant?.modelUrl ?? model.texturedModelUrl ?? null,
      baseColorTextureUrl: model.editedVariant?.baseColorUrl ?? model.textureMaps?.baseColor ?? null,
      editedVariant: model.editedVariant,
      engineering,
      passenger,
      recommendation,
      starredBy: [],
    };
  });
};

export const RECOMMENDATION_CONFIG: Record<
  RecommendationLevel,
  {
    label: string;
    icon: string;
    color: string;
    bgColor: string;
  }
> = {
  highly_recommended: {
    label: 'Highly Recommended',
    icon: '+++',
    color: 'text-emerald-700',
    bgColor: 'bg-emerald-50 border-emerald-200',
  },
  recommended: {
    label: 'Recommended',
    icon: '++',
    color: 'text-blue-700',
    bgColor: 'bg-blue-50 border-blue-200',
  },
  acceptable: {
    label: 'Acceptable',
    icon: '+',
    color: 'text-amber-700',
    bgColor: 'bg-amber-50 border-amber-200',
  },
  not_recommended: {
    label: 'Not Recommended',
    icon: 'x',
    color: 'text-rose-700',
    bgColor: 'bg-rose-50 border-rose-200',
  },
};
