import type {
  BaseModelMeta,
  EngineeringAssessment,
  PassengerAssessment,
  RecommendationLevel,
  ReviewScheme,
  TexturedModel,
} from '../types/design.ts';
import type { MeetingSettings } from '../types/meeting.ts';

const FALLBACK_SCHEME_NAMES = [
  '冰雪流线',
  '雪境渐变',
  '融合图案',
  '蔚蓝波纹',
  '晶体线条',
  '北境光带',
];

export const buildReviewSchemes = (
  texturedModels: TexturedModel[],
  _baseModel: BaseModelMeta | null,
  meetingSettings: MeetingSettings | null,
): ReviewScheme[] => {
  const completedModels = texturedModels.filter((model) => model.status === 'completed');
  const passengerLabel =
    meetingSettings?.reviewPersonas.roles.find((role) => role.type === 'passenger' && role.enabled)?.displayName ??
    meetingSettings?.reviewPersonas.passenger.displayName ??
    '普通乘客';
  const engineeringLabel =
    meetingSettings?.reviewPersonas.roles.find((role) => role.type === 'engineering' && role.enabled)?.displayName ??
    meetingSettings?.reviewPersonas.engineering.displayName ??
    '工程评审';
  const currentSettingsRevision = meetingSettings?.revision ?? 1;

  return completedModels.map((model, index) => {
    const hasCompletedReview =
      model.reviewAssessment?.status === 'completed' &&
      model.reviewAssessment.source === 'llm' &&
      Boolean(model.reviewAssessment.engineering) &&
      Boolean(model.reviewAssessment.passenger) &&
      Boolean(model.reviewAssessment.recommendation);

    const reviewModelName = model.reviewAssessment?.modelName ?? null;
    const reviewStatus = hasCompletedReview
      ? 'completed'
      : (model.reviewAssessment?.status ?? 'pending');
    const reviewSource = model.reviewAssessment?.source ?? null;
    const reviewErrorMessage =
      model.reviewAssessment?.errorMessage ??
      (reviewStatus === 'failed' ? '阶段三评审请求失败。' : null);
    const reviewSettingsRevisionUsed = model.reviewAssessment?.settingsRevisionUsed ?? null;
    const reviewPersonaLabelsUsed = model.reviewAssessment?.personaLabelsUsed ?? null;
    const reviewSettingsStale =
      reviewStatus === 'completed' &&
      reviewSettingsRevisionUsed !== null &&
      reviewSettingsRevisionUsed !== currentSettingsRevision;

    return {
      id: `review_${model.resultId}`,
      resultId: model.resultId,
      batchId: model.batchId,
      sourceType: model.sourceType,
      createdAt: model.createdAt,
      familyId: model.familyId,
      parentResultId: model.parentResultId,
      name: model.title || FALLBACK_SCHEME_NAMES[index % FALLBACK_SCHEME_NAMES.length] || `方案 ${index + 1}`,
      author: model.submittedBy?.userName ?? model.sharedOrigin?.userName ?? '当前用户',
      submittedByUserId: model.submittedBy?.userId ?? null,
      submittedByName: model.submittedBy?.userName ?? null,
      groupTitle: model.title || FALLBACK_SCHEME_NAMES[index % FALLBACK_SCHEME_NAMES.length] || `方案 ${index + 1}`,
      schemeId: model.schemeId,
      texturedModelUrl: model.editedVariant?.modelUrl ?? model.texturedModelUrl ?? null,
      baseColorTextureUrl: model.editedVariant?.baseColorUrl ?? model.textureMaps?.baseColor ?? null,
      editedVariant: model.editedVariant,
      engineering: hasCompletedReview ? (model.reviewAssessment?.engineering as EngineeringAssessment) : null,
      passenger: hasCompletedReview ? (model.reviewAssessment?.passenger as PassengerAssessment) : null,
      recommendation: hasCompletedReview ? (model.reviewAssessment?.recommendation as RecommendationLevel) : null,
      overallNarrative: hasCompletedReview ? (model.reviewAssessment?.overallNarrative ?? null) : null,
      reviewStatus,
      reviewSource,
      reviewModelName,
      reviewErrorMessage,
      reviewSettingsRevisionUsed,
      reviewSettingsStale,
      passengerLabel,
      engineeringLabel,
      reviewPersonaLabelsUsed,
      roleReviews: model.reviewAssessment?.roleReviews ?? [],
      starredBy: [],
      sharedOrigin: model.sharedOrigin,
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
    label: '强烈推荐',
    icon: '+++',
    color: 'text-emerald-700',
    bgColor: 'bg-emerald-50 border-emerald-200',
  },
  recommended: {
    label: '推荐',
    icon: '++',
    color: 'text-blue-700',
    bgColor: 'bg-blue-50 border-blue-200',
  },
  acceptable: {
    label: '可接受',
    icon: '+',
    color: 'text-amber-700',
    bgColor: 'bg-amber-50 border-amber-200',
  },
  not_recommended: {
    label: '不推荐',
    icon: 'x',
    color: 'text-rose-700',
    bgColor: 'bg-rose-50 border-rose-200',
  },
};
