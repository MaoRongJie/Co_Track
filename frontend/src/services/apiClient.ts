import axios from 'axios';
import type {
  BaseModelMeta,
  BaseModelSource,
  BriefKeywordSnapshot,
  DesignBrief,
  ProductCategory,
  ProductProfile,
  SubmittedByInfo,
  TexturedModel,
  TextureModelsState,
  TexturePlanState,
} from '../types/design.ts';
import type {
  AuthResponse,
  AuthUser,
  IceConfigResponse,
  JoinSessionResponse,
  JoinedSession,
  MeetingSettings,
  MeetingSettingsPermissions,
  MeetingSettingsSection,
  MeetingSettingsState,
  MeetingRole,
  SessionMemberDirectoryEntry,
  SessionMembersResponse,
  SessionStage,
} from '../types/meeting.ts';

const DEFAULT_API_PORT = '8000';

const normalizeApiHostname = (hostname: string): string => {
  const normalized = hostname.trim().toLowerCase();
  if (
    normalized.length === 0 ||
    normalized === 'localhost' ||
    normalized === '::1' ||
    normalized === '[::1]' ||
    normalized === '0.0.0.0'
  ) {
    return '127.0.0.1';
  }
  return hostname;
};

const detectDefaultApiBaseUrl = (): string => {
  if (typeof window === 'undefined') {
    return `http://127.0.0.1:${DEFAULT_API_PORT}`;
  }

  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  const hostname = normalizeApiHostname(window.location.hostname);

  return `${protocol}//${hostname}:${DEFAULT_API_PORT}`;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? detectDefaultApiBaseUrl();
const AI_IMAGE_REQUEST_TIMEOUT_MS = 180000;
const STAGE4_MEDIA_REQUEST_TIMEOUT_MS = 600000;

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
});

const normalizeEmailName = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '') || 'designer';

const authHeader = (token: string) => ({
  headers: { Authorization: `Bearer ${token}` },
});

const toAbsoluteApiUrl = (path: string): string => {
  const normalizedBase = API_BASE_URL.endsWith('/') ? API_BASE_URL : `${API_BASE_URL}/`;
  const normalizedPath = path.startsWith('/') ? path.slice(1) : path;
  return new URL(normalizedPath, normalizedBase).toString();
};

const login = async (email: string, password: string): Promise<AuthResponse> => {
  const response = await api.post<AuthResponse>('/api/auth/login', { email, password });
  return response.data;
};

const register = async (email: string, name: string, password: string): Promise<AuthResponse> => {
  const response = await api.post<AuthResponse>('/api/auth/register', { email, name, password });
  return response.data;
};

export const ensureUserToken = async (
  displayName: string,
  password: string,
  identitySeed = '',
): Promise<{ token: string; user: AuthUser }> => {
  const local = normalizeEmailName(displayName);
  void identitySeed;
  const email = `${local}@co-track.local`;

  try {
    const logged = await login(email, password);
    return { token: logged.access_token, user: logged.user };
  } catch {
    await register(email, displayName, password);
    const logged = await login(email, password);
    return { token: logged.access_token, user: logged.user };
  }
};

export const joinSessionByInvite = async (
  token: string,
  inviteCode: string,
  role: MeetingRole,
): Promise<JoinSessionResponse> => {
  const response = await api.post<{
    session: BackendJoinedSession;
    role: MeetingRole;
  }>(
    '/api/sessions/join',
    { invite_code: inviteCode, role },
    authHeader(token),
  );
  return {
    session: mapBackendJoinedSession(response.data.session),
    role: response.data.role,
  };
};

export const fetchSessionDetail = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.get<BackendJoinedSession>(`/api/sessions/${sessionId}`, authHeader(token));
  return mapBackendJoinedSession(response.data);
};

export const fetchSessionSettings = async (token: string, sessionId: number): Promise<MeetingSettingsState> => {
  const response = await api.get<BackendMeetingSettingsState>(
    `/api/sessions/${sessionId}/settings`,
    authHeader(token),
  );
  return mapBackendMeetingSettingsState(response.data);
};

export const patchSessionSettings = async (
  token: string,
  sessionId: number,
  settings: MeetingSettings,
): Promise<MeetingSettingsState> => {
  const response = await api.patch<BackendMeetingSettingsState>(
    `/api/sessions/${sessionId}/settings`,
    {
      review_personas: {
        roles: settings.reviewPersonas.roles.map((role) => ({
          id: role.id,
          type: role.type,
          enabled: role.enabled,
          display_name: role.displayName,
          identity_summary: role.identitySummary,
          role_prompt: role.rolePrompt ?? null,
          focus_points: role.focusPoints,
          preference_tags: role.preferenceTags,
          dislike_tags: role.dislikeTags,
          priority_tags: role.priorityTags,
          risk_focus: role.riskFocus,
        })),
      },
    },
    authHeader(token),
  );
  return mapBackendMeetingSettingsState(response.data);
};

type BackendSessionMemberDirectoryEntry = {
  user_id: number;
  name: string;
  role: MeetingRole;
  joined_at: string;
  online: boolean;
  public_share_count: number;
  can_live_sync: boolean;
  shared_result_ids: string[];
};

type BackendMeetingSettings = {
  revision: number;
  updated_at: string | null;
  updated_by_user_id: number | null;
  review_personas: {
    passenger: {
      display_name: string;
      identity_summary: string;
      preference_tags: string[];
      dislike_tags: string[];
      focus_points: string[];
    };
    engineering: {
      display_name: string;
      identity_summary: string;
      priority_tags: string[];
      risk_focus: string[];
      focus_points: string[];
    };
    roles?: BackendReviewPersonaRole[];
  };
};

type BackendReviewPersonaRole = {
  id: string;
  type: 'passenger' | 'engineering' | 'custom';
  enabled: boolean;
  display_name: string;
  identity_summary: string;
  role_prompt?: string | null;
  focus_points: string[];
  preference_tags: string[];
  dislike_tags: string[];
  priority_tags: string[];
  risk_focus: string[];
};

type BackendMeetingSettingsPermissions = {
  role: MeetingRole;
  can_edit: boolean;
};

type BackendMeetingSettingsSection = {
  id: MeetingSettingsSection['id'];
  label: string;
  description: string;
  enabled: boolean;
  badge: string | null;
};

type BackendJoinedSession = Omit<JoinedSession, 'session_settings' | 'settings_permissions' | 'settings_sections'> & {
  session_settings?: BackendMeetingSettings | null;
  settings_permissions?: BackendMeetingSettingsPermissions | null;
  settings_sections?: BackendMeetingSettingsSection[] | null;
};

type BackendMeetingSettingsState = {
  session_id: number;
  session_settings: BackendMeetingSettings;
  settings_permissions: BackendMeetingSettingsPermissions;
  sections: BackendMeetingSettingsSection[];
};

const mapBackendMeetingSettings = (value: BackendMeetingSettings | null | undefined): MeetingSettings | null => {
  if (!value) {
    return null;
  }
  const passenger = {
    displayName: value.review_personas?.passenger?.display_name ?? '普通乘客',
    identitySummary: value.review_personas?.passenger?.identity_summary ?? '',
    preferenceTags: value.review_personas?.passenger?.preference_tags ?? [],
    dislikeTags: value.review_personas?.passenger?.dislike_tags ?? [],
    focusPoints: value.review_personas?.passenger?.focus_points ?? [],
  };
  const engineering = {
    displayName: value.review_personas?.engineering?.display_name ?? '工程评审',
    identitySummary: value.review_personas?.engineering?.identity_summary ?? '',
    priorityTags: value.review_personas?.engineering?.priority_tags ?? [],
    riskFocus: value.review_personas?.engineering?.risk_focus ?? [],
    focusPoints: value.review_personas?.engineering?.focus_points ?? [],
  };
  const roles = value.review_personas?.roles?.length
    ? value.review_personas.roles.map((role) => ({
        id: role.id,
        type: role.type,
        enabled: role.enabled,
        displayName: role.display_name,
        identitySummary: role.identity_summary,
        rolePrompt: role.role_prompt?.trim() ? role.role_prompt : null,
        focusPoints: role.focus_points ?? [],
        preferenceTags: role.preference_tags ?? [],
        dislikeTags: role.dislike_tags ?? [],
        priorityTags: role.priority_tags ?? [],
        riskFocus: role.risk_focus ?? [],
      }))
    : [
        {
          id: 'passenger_default',
          type: 'passenger' as const,
          enabled: true,
          displayName: passenger.displayName,
          identitySummary: passenger.identitySummary,
          rolePrompt: null,
          focusPoints: passenger.focusPoints,
          preferenceTags: passenger.preferenceTags,
          dislikeTags: passenger.dislikeTags,
          priorityTags: [],
          riskFocus: [],
        },
        {
          id: 'engineering_default',
          type: 'engineering' as const,
          enabled: true,
          displayName: engineering.displayName,
          identitySummary: engineering.identitySummary,
          rolePrompt: null,
          focusPoints: engineering.focusPoints,
          preferenceTags: [],
          dislikeTags: [],
          priorityTags: engineering.priorityTags,
          riskFocus: engineering.riskFocus,
        },
      ];
  return {
    revision: value.revision ?? 1,
    updatedAt: value.updated_at ?? null,
    updatedByUserId: value.updated_by_user_id ?? null,
    reviewPersonas: {
      passenger,
      engineering,
      roles,
    },
  };
};

const mapBackendMeetingSettingsPermissions = (
  value: BackendMeetingSettingsPermissions | null | undefined,
): MeetingSettingsPermissions | null => {
  if (!value) {
    return null;
  }
  return {
    role: value.role,
    canEdit: Boolean(value.can_edit),
  };
};

const mapBackendMeetingSettingsSections = (
  value: BackendMeetingSettingsSection[] | null | undefined,
): MeetingSettingsSection[] => (value ?? []).map((item) => ({
  id: item.id,
  label: item.label,
  description: item.description,
  enabled: item.enabled,
  badge: item.badge ?? null,
}));

const mapBackendJoinedSession = (value: BackendJoinedSession): JoinedSession => ({
  ...value,
  session_settings: mapBackendMeetingSettings(value.session_settings),
  settings_permissions: mapBackendMeetingSettingsPermissions(value.settings_permissions),
  settings_sections: mapBackendMeetingSettingsSections(value.settings_sections),
});

const mapBackendMeetingSettingsState = (value: BackendMeetingSettingsState): MeetingSettingsState => ({
  sessionId: value.session_id,
  sessionSettings: mapBackendMeetingSettings(value.session_settings)!,
  settingsPermissions: mapBackendMeetingSettingsPermissions(value.settings_permissions)!,
  sections: mapBackendMeetingSettingsSections(value.sections),
});

const mapBackendSessionMemberDirectoryEntry = (
  item: BackendSessionMemberDirectoryEntry,
): SessionMemberDirectoryEntry => ({
  userId: item.user_id,
  name: item.name,
  role: item.role,
  joinedAt: item.joined_at,
  online: item.online,
  publicShareCount: item.public_share_count,
  canLiveSync: item.can_live_sync,
  sharedResultIds: item.shared_result_ids ?? [],
});

export const fetchSessionMembers = async (token: string, sessionId: number): Promise<SessionMembersResponse> => {
  const response = await api.get<{
    session_id: number;
    members: BackendSessionMemberDirectoryEntry[];
  }>(`/api/sessions/${sessionId}/members`, authHeader(token));
  return {
    sessionId: response.data.session_id,
    members: (response.data.members ?? []).map(mapBackendSessionMemberDirectoryEntry),
  };
};

export const advanceSessionStage = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.post<BackendJoinedSession>(`/api/sessions/${sessionId}/advance`, {}, authHeader(token));
  return mapBackendJoinedSession(response.data);
};

export const revertSessionStage = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.post<BackendJoinedSession>(`/api/sessions/${sessionId}/revert`, {}, authHeader(token));
  return mapBackendJoinedSession(response.data);
};

export const fetchRtcConfig = async (token: string): Promise<IceConfigResponse> => {
  const response = await api.get<IceConfigResponse>('/api/rtc/config', authHeader(token));
  return response.data;
};

type BackendModelAsset = {
  id: number;
  name: string;
  source_type: BaseModelSource;
  precision_level: BaseModelMeta['precisionLevel'];
  license_scope: BaseModelMeta['licenseScope'];
  export_glb_allowed: boolean;
  model_url: string;
  uv_template_url: string;
  surface_area_m2: number;
  paintable_uv_pixels: number;
  mapping_meta?: {
    inspection?: {
      file_name?: string;
      format?: string;
      mesh_count?: number;
      material_count?: number;
      bbox_m?: number[];
      has_original_uv?: boolean;
      uv_source?: string;
      uv_template_mode?: string;
      warnings?: string[];
    };
    uv_spec?: {
      width?: number;
      height?: number;
      paintable_uv_pixels?: number;
    };
    mesh_to_region?: Record<string, string>;
  } | null;
  created_at: string;
};

const toSafeNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
};

const mapBackendModelAsset = (asset: BackendModelAsset, lockedAt?: string | null): BaseModelMeta => ({
  baseModelId: asset.id,
  sourceType: asset.source_type,
  precisionLevel: asset.precision_level,
  modelUrl: asset.model_url.startsWith('/') ? toAbsoluteApiUrl(asset.model_url) : asset.model_url,
  uvTemplateUrl: asset.uv_template_url.startsWith('/') ? toAbsoluteApiUrl(asset.uv_template_url) : asset.uv_template_url,
  surfaceAreaM2: toSafeNumber(asset.surface_area_m2),
  paintableUvPixels: Math.round(toSafeNumber(asset.paintable_uv_pixels)),
  exportGlbAllowed: asset.export_glb_allowed,
  licenseScope: asset.license_scope,
  lockedAt: lockedAt ?? undefined,
  mappingMeta: asset.mapping_meta
    ? {
      inspection: asset.mapping_meta.inspection
        ? {
          fileName: asset.mapping_meta.inspection.file_name,
          format: asset.mapping_meta.inspection.format,
          meshCount: asset.mapping_meta.inspection.mesh_count,
          materialCount: asset.mapping_meta.inspection.material_count,
          bboxM: asset.mapping_meta.inspection.bbox_m,
          hasOriginalUv: asset.mapping_meta.inspection.has_original_uv,
          uvSource: asset.mapping_meta.inspection.uv_source,
          uvTemplateMode: asset.mapping_meta.inspection.uv_template_mode,
          warnings: asset.mapping_meta.inspection.warnings,
        }
        : undefined,
      uvSpec: asset.mapping_meta.uv_spec
        ? {
          width: asset.mapping_meta.uv_spec.width,
          height: asset.mapping_meta.uv_spec.height,
          paintableUvPixels: asset.mapping_meta.uv_spec.paintable_uv_pixels,
        }
        : undefined,
      meshToRegion: asset.mapping_meta.mesh_to_region,
    }
    : undefined,
});

type BackendGeneratedImage = {
  id: number;
  session_id: number;
  prompt: string;
  style_hint: string | null;
  revised_prompt: string | null;
  image_url: string;
  created_at: string;
};

type BackendGeneratedMediaAsset = {
  id: number;
  session_id: number;
  result_id: string | null;
  scheme_name: string | null;
  media_type: 'image' | 'video';
  media_url: string;
  prompt: string;
  provider: string;
  model_name: string;
  prediction_id: string | null;
  source_image_url: string | null;
  can_delete: boolean;
  created_at: string;
};

type BackendTexturePatternGenerateResponse = {
  item: BackendGeneratedImage;
  analysis_summary: string;
  dominant_colors: string[];
  source_result_id: string;
  pattern_prompt_text: string | null;
};

type BackendStage4SceneImageResponse = {
  session_id: number;
  result_id: string | null;
  image_url: string;
  image_prediction_id: string;
  image_prompt: string;
  created_image: BackendGeneratedImage | null;
  media_asset: BackendGeneratedMediaAsset | null;
};

type BackendStage4SceneVideoResponse = {
  session_id: number;
  result_id: string | null;
  video_url: string;
  video_prediction_id: string;
  video_prompt: string;
  media_asset: BackendGeneratedMediaAsset | null;
};

type BackendTexturePlanState = {
  session_id: number;
  source_text: string;
  document_name: string | null;
  document_excerpt: string;
  image_name: string | null;
  image_content_keywords: string[];
  image_style_keywords: string[];
  selected_image_keywords: string[];
  brief_keywords: BriefKeywordSnapshot;
  updated_at: string;
};

const mapMediaUrl = (value: string): string => (value.startsWith('/') ? toAbsoluteApiUrl(value) : value);

const mapBackendGeneratedImage = (item: BackendGeneratedImage): GeneratedPatternImage => ({
  id: item.id,
  sessionId: item.session_id,
  prompt: item.prompt,
  styleHint: item.style_hint,
  revisedPrompt: item.revised_prompt,
  imageUrl: mapMediaUrl(item.image_url),
  createdAt: item.created_at,
});

const mapBackendGeneratedMediaAsset = (item: BackendGeneratedMediaAsset): Stage4MediaAsset => ({
  id: item.id,
  sessionId: item.session_id,
  resultId: item.result_id,
  schemeName: item.scheme_name,
  mediaType: item.media_type,
  mediaUrl: mapMediaUrl(item.media_url),
  prompt: item.prompt,
  provider: item.provider,
  modelName: item.model_name,
  predictionId: item.prediction_id,
  sourceImageUrl: item.source_image_url ? mapMediaUrl(item.source_image_url) : null,
  canDelete: item.can_delete,
  createdAt: item.created_at,
});

const mapBackendTexturePlanState = (item: BackendTexturePlanState): TexturePlanState => ({
  sessionId: item.session_id,
  sourceText: item.source_text,
  documentName: item.document_name,
  documentExcerpt: item.document_excerpt,
  imageName: item.image_name,
  imageContentKeywords: item.image_content_keywords ?? [],
  imageStyleKeywords: item.image_style_keywords ?? [],
  selectedImageKeywords: item.selected_image_keywords ?? [],
  briefKeywords: item.brief_keywords,
  updatedAt: item.updated_at,
});

export type ModelLibraryItem = {
  id: number;
  name: string;
  baseModel: BaseModelMeta;
};

export type ParseBriefPayload = {
  sessionId: number;
  designGoal: string;
  productCategory: ProductCategory;
};

export type GeneratedPatternImage = {
  id: number;
  sessionId: number;
  prompt: string;
  styleHint: string | null;
  revisedPrompt: string | null;
  imageUrl: string;
  createdAt: string;
};

export type GeneratedPatternPreview = {
  item: GeneratedPatternImage;
  analysisSummary: string;
  dominantColors: string[];
  sourceResultId: string;
  patternPromptText: string | null;
};

export type Stage4SceneImageResult = {
  sessionId: number;
  resultId: string | null;
  imageUrl: string;
  imagePredictionId: string;
  imagePrompt: string;
  createdImage: GeneratedPatternImage | null;
  mediaAsset: Stage4MediaAsset | null;
};

export type Stage4SceneVideoResult = {
  sessionId: number;
  resultId: string | null;
  videoUrl: string;
  videoPredictionId: string;
  videoPrompt: string;
  mediaAsset: Stage4MediaAsset | null;
};

export type Stage4MediaAsset = {
  id: number;
  sessionId: number;
  resultId: string | null;
  schemeName: string | null;
  mediaType: 'image' | 'video';
  mediaUrl: string;
  prompt: string;
  provider: string;
  modelName: string;
  predictionId: string | null;
  sourceImageUrl: string | null;
  canDelete: boolean;
  createdAt: string;
};

export const fetchTexturePlan = async (token: string, sessionId: number): Promise<TexturePlanState> => {
  const response = await api.get<BackendTexturePlanState>('/api/ai/texture-plan', {
    ...authHeader(token),
    params: { session_id: sessionId },
  });
  return mapBackendTexturePlanState(response.data);
};

export const analyzeTexturePlanImage = async (
  token: string,
  payload: {
    sessionId: number;
    referenceImageFile: File;
  },
): Promise<TexturePlanState> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  formData.append('reference_image', payload.referenceImageFile);

  const response = await api.post<BackendTexturePlanState>('/api/ai/texture-plan/analyze-image', formData, {
    ...authHeader(token),
    headers: {
      ...authHeader(token).headers,
      'Content-Type': 'multipart/form-data',
    },
    timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
  });
  return mapBackendTexturePlanState(response.data);
};

export const generateTexturePlan = async (
  token: string,
  payload: {
    sessionId: number;
    sourceText?: string;
    documentFile?: File | null;
    referenceImageFile?: File | null;
    selectedImageKeywords?: string[];
  },
): Promise<TexturePlanState> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  if (payload.sourceText && payload.sourceText.trim().length > 0) {
    formData.append('source_text', payload.sourceText);
  }
  if (payload.documentFile) {
    formData.append('document', payload.documentFile);
  }
  if (payload.referenceImageFile) {
    formData.append('reference_image', payload.referenceImageFile);
  }
  if (payload.selectedImageKeywords) {
    formData.append('selected_image_keywords_json', JSON.stringify(payload.selectedImageKeywords));
  }

  const response = await api.post<{ texture_plan: BackendTexturePlanState }>('/api/ai/texture-plan/generate', formData, {
    ...authHeader(token),
    headers: {
      ...authHeader(token).headers,
      'Content-Type': 'multipart/form-data',
    },
    timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
  });
  return mapBackendTexturePlanState(response.data.texture_plan);
};

export const patchTexturePlan = async (
  token: string,
  payload: {
    sessionId: number;
    selectedImageKeywords?: string[];
    clearDocument?: boolean;
    clearImage?: boolean;
  },
): Promise<TexturePlanState> => {
  const response = await api.patch<BackendTexturePlanState>(
    '/api/ai/texture-plan',
    {
      session_id: payload.sessionId,
      selected_image_keywords: payload.selectedImageKeywords,
      clear_document: payload.clearDocument,
      clear_image: payload.clearImage,
    },
    authHeader(token),
  );
  return mapBackendTexturePlanState(response.data);
};

type BackendTexturedModel = {
  result_id: string;
  batch_id: string | null;
  source_type: TexturedModel['sourceType'];
  created_at: string;
  family_id: string;
  parent_result_id: string | null;
  scheme_id: string;
  title: string;
  prompt_text: string;
  status: string;
  textured_model_url: string | null;
  texture_maps: {
    base_color?: string | null;
    metallic?: string | null;
    normal?: string | null;
    roughness?: string | null;
  } | null;
  edited_variant: {
    model_url: string;
    base_color_url: string;
    applied_at: string;
  } | null;
  review_assessment: {
    status?: 'completed' | 'failed';
    engineering?: {
      paint_volume_kg: number;
      color_zone_count: number;
      masking_steps: number;
      gradient_ratio_percent: number;
      labor_hours: number;
      process_steps: number;
      curve_conformance_score: number;
      material_cost_yuan: number;
      labor_cost_yuan: number;
      total_cost_yuan: number;
      color_variance_risk: 'HIGH' | 'MEDIUM' | 'LOW';
      weather_durability: 'A' | 'B' | 'C';
      maintenance_cycle_years: number;
      summary?: string | null;
      quick_comment?: string | null;
    } | null;
    passenger?: {
      scores?: {
        first_impression: number;
        safety_trust: number;
        comfort_cleanliness: number;
        perceived_quality: number;
        speed_motion: number;
        emotion_character: number;
      } | null;
      overall_score?: number;
      summary?: string | null;
      quick_comment?: string | null;
      strengths?: string[] | null;
      issues?: string[] | null;
      suggestions?: string[] | null;
    } | null;
    role_reviews?: {
      role_id: string;
      role_type: 'passenger' | 'engineering' | 'custom';
      role_name: string;
      assessment: Record<string, unknown>;
    }[] | null;
    recommendation?: 'highly_recommended' | 'recommended' | 'acceptable' | 'not_recommended' | null;
    overall_narrative?: string | null;
    source?: 'llm' | 'failed';
    model_name?: string | null;
    error_message?: string | null;
    settings_revision_used?: number | null;
    persona_labels_used?: {
      passenger: string;
      engineering: string;
    } | null;
  } | null;
  meshy_task_id: string | null;
  error_message: string | null;
  shared_origin: {
    user_id: number;
    user_name: string;
    source_result_id: string;
  } | null;
  submitted_by: {
    user_id: number;
    user_name: string;
  } | null;
};

type BackendTextureModelsState = {
  session_id: number;
  status: TextureModelsState['status'];
  models: BackendTexturedModel[];
  updated_at: string;
};

const mapBackendReviewAssessment = (
  review: BackendTexturedModel['review_assessment'],
): TexturedModel['reviewAssessment'] => {
  if (!review) {
    return null;
  }

  const rawSource = review.source ?? null;
  const hasCompletePayload = Boolean(review.engineering && review.passenger && review.recommendation);
  const hasPassengerScores = Boolean(review.passenger?.scores);
  const isCompletedReview =
    (review.status === 'completed' || review.status == null) &&
    rawSource === 'llm' &&
    hasCompletePayload &&
    hasPassengerScores;

  return {
    status: isCompletedReview ? 'completed' : 'failed',
    engineering: isCompletedReview
      ? {
          paintVolumeKg: review.engineering!.paint_volume_kg,
          colorZoneCount: review.engineering!.color_zone_count,
          maskingSteps: review.engineering!.masking_steps,
          gradientRatioPercent: review.engineering!.gradient_ratio_percent,
          laborHours: review.engineering!.labor_hours,
          processSteps: review.engineering!.process_steps,
          curveConformanceScore: review.engineering!.curve_conformance_score,
          materialCostYuan: review.engineering!.material_cost_yuan,
          laborCostYuan: review.engineering!.labor_cost_yuan,
          totalCostYuan: review.engineering!.total_cost_yuan,
          colorVarianceRisk: review.engineering!.color_variance_risk,
          weatherDurability: review.engineering!.weather_durability,
          maintenanceCycleYears: review.engineering!.maintenance_cycle_years,
          summary: review.engineering!.summary ?? null,
          quickComment: review.engineering!.quick_comment ?? null,
        }
      : null,
    passenger: isCompletedReview
      ? {
          scores: {
            firstImpression: review.passenger!.scores!.first_impression,
            safetyTrust: review.passenger!.scores!.safety_trust,
            comfortCleanliness: review.passenger!.scores!.comfort_cleanliness,
            perceivedQuality: review.passenger!.scores!.perceived_quality,
            speedMotion: review.passenger!.scores!.speed_motion,
            emotionCharacter: review.passenger!.scores!.emotion_character,
          },
          overallScore: review.passenger!.overall_score ?? 0,
          summary: review.passenger!.summary ?? '',
          quickComment: review.passenger!.quick_comment ?? null,
          strengths: Array.isArray(review.passenger!.strengths) ? review.passenger!.strengths : [],
          issues: Array.isArray(review.passenger!.issues) ? review.passenger!.issues : [],
          suggestions: Array.isArray(review.passenger!.suggestions) ? review.passenger!.suggestions : [],
        }
      : null,
    roleReviews: Array.isArray(review.role_reviews)
      ? review.role_reviews.map((item) => ({
          roleId: item.role_id,
          roleType: item.role_type,
          roleName: item.role_name,
          assessment: item.assessment,
        }))
      : [],
    recommendation: isCompletedReview ? review.recommendation ?? null : null,
    overallNarrative: isCompletedReview ? review.overall_narrative ?? null : null,
    source: rawSource ?? 'failed',
    modelName: review.model_name ?? null,
    errorMessage: review.error_message ?? null,
    settingsRevisionUsed: review.settings_revision_used ?? null,
    personaLabelsUsed: review.persona_labels_used ?? null,
  };
};

const mapBackendSharedOrigin = (origin: BackendTexturedModel['shared_origin']): TexturedModel['sharedOrigin'] => {
  if (!origin) {
    return null;
  }
  return {
    userId: origin.user_id,
    userName: origin.user_name,
    sourceResultId: origin.source_result_id,
  };
};

const mapBackendSubmittedBy = (submittedBy: BackendTexturedModel['submitted_by']): SubmittedByInfo | null => {
  if (!submittedBy) {
    return null;
  }
  return {
    userId: submittedBy.user_id,
    userName: submittedBy.user_name,
  };
};

const mapBackendTexturedModel = (item: BackendTexturedModel): TexturedModel => ({
  resultId: item.result_id,
  batchId: item.batch_id ?? null,
  sourceType: item.source_type,
  createdAt: item.created_at,
  familyId: item.family_id || item.result_id,
  parentResultId: item.parent_result_id ?? null,
  schemeId: item.scheme_id as TexturedModel['schemeId'],
  title: item.title,
  promptText: item.prompt_text,
  status: item.status as TexturedModel['status'],
  texturedModelUrl: item.textured_model_url?.startsWith('/') ? toAbsoluteApiUrl(item.textured_model_url) : item.textured_model_url,
  textureMaps: item.texture_maps
    ? {
        baseColor: item.texture_maps.base_color?.startsWith('/')
          ? toAbsoluteApiUrl(item.texture_maps.base_color)
          : (item.texture_maps.base_color ?? null),
        metallic: item.texture_maps.metallic?.startsWith('/')
          ? toAbsoluteApiUrl(item.texture_maps.metallic)
          : (item.texture_maps.metallic ?? null),
        normal: item.texture_maps.normal?.startsWith('/')
          ? toAbsoluteApiUrl(item.texture_maps.normal)
          : (item.texture_maps.normal ?? null),
        roughness: item.texture_maps.roughness?.startsWith('/')
          ? toAbsoluteApiUrl(item.texture_maps.roughness)
          : (item.texture_maps.roughness ?? null),
      }
    : null,
  editedVariant: item.edited_variant
    ? {
        modelUrl: item.edited_variant.model_url.startsWith('/')
          ? toAbsoluteApiUrl(item.edited_variant.model_url)
          : item.edited_variant.model_url,
        baseColorUrl: item.edited_variant.base_color_url.startsWith('/')
          ? toAbsoluteApiUrl(item.edited_variant.base_color_url)
          : item.edited_variant.base_color_url,
        appliedAt: item.edited_variant.applied_at,
      }
    : null,
  reviewAssessment: mapBackendReviewAssessment(item.review_assessment),
  meshyTaskId: item.meshy_task_id,
  errorMessage: item.error_message,
  sharedOrigin: mapBackendSharedOrigin(item.shared_origin),
  submittedBy: mapBackendSubmittedBy(item.submitted_by),
});

const mapBackendTextureModelsState = (item: BackendTextureModelsState): TextureModelsState => ({
  sessionId: item.session_id,
  status: item.status,
  models: item.models.map(mapBackendTexturedModel),
  updatedAt: item.updated_at,
});

export const fetchTextureModels = async (
  token: string,
  payload: { sessionId: number },
): Promise<TextureModelsState> => {
  const response = await api.get<BackendTextureModelsState>('/api/ai/texture-plan/models', {
    ...authHeader(token),
    params: { session_id: payload.sessionId },
  });
  return mapBackendTextureModelsState(response.data);
};

export const deleteTextureModel = async (
  token: string,
  payload: { sessionId: number; resultId: string },
): Promise<TextureModelsState> => {
  const response = await api.delete<BackendTextureModelsState>(
    `/api/ai/texture-plan/models/${encodeURIComponent(payload.resultId)}`,
    {
      ...authHeader(token),
      params: { session_id: payload.sessionId },
    },
  );
  return mapBackendTextureModelsState(response.data);
};

export const shareTextureResults = async (
  token: string,
  payload: { sessionId: number; resultIds: string[] },
): Promise<{ sessionId: number; sharedResultIds: string[]; updatedAt: string }> => {
  const response = await api.post<{
    session_id: number;
    shared_result_ids: string[];
    updated_at: string;
  }>(
    '/api/ai/texture-plan/share-results',
    {
      session_id: payload.sessionId,
      result_ids: payload.resultIds,
    },
    authHeader(token),
  );
  return {
    sessionId: response.data.session_id,
    sharedResultIds: response.data.shared_result_ids ?? [],
    updatedAt: response.data.updated_at,
  };
};

export const fetchSharedTextureResults = async (
  token: string,
  payload: { sessionId: number; sourceUserId: number },
): Promise<{ sessionId: number; sourceUserId: number; sourceUserName: string; models: TexturedModel[]; updatedAt: string }> => {
  const response = await api.get<{
    session_id: number;
    source_user_id: number;
    source_user_name: string;
    models: BackendTexturedModel[];
    updated_at: string;
  }>('/api/ai/texture-plan/shared-results', {
    ...authHeader(token),
    params: {
      session_id: payload.sessionId,
      member_user_id: payload.sourceUserId,
    },
  });
  return {
    sessionId: response.data.session_id,
    sourceUserId: response.data.source_user_id,
    sourceUserName: response.data.source_user_name,
    models: (response.data.models ?? []).map(mapBackendTexturedModel),
    updatedAt: response.data.updated_at,
  };
};

export const fetchStage3SharedTextureModels = async (
  token: string,
  payload: { sessionId: number },
): Promise<TextureModelsState> => {
  const response = await api.get<BackendTextureModelsState>('/api/ai/texture-plan/stage3-shared-models', {
    ...authHeader(token),
    params: { session_id: payload.sessionId },
  });
  return mapBackendTextureModelsState(response.data);
};

export const importSharedTextureResults = async (
  token: string,
  payload: { sessionId: number; sourceUserId: number; resultIds: string[] },
): Promise<TextureModelsState> => {
  const response = await api.post<BackendTextureModelsState>(
    '/api/ai/texture-plan/import-shared-results',
    {
      session_id: payload.sessionId,
      source_user_id: payload.sourceUserId,
      result_ids: payload.resultIds,
    },
    authHeader(token),
  );
  return mapBackendTextureModelsState(response.data);
};

export const refreshTextureModelReview = async (
  token: string,
  payload: { sessionId: number; resultId?: string | null },
): Promise<TextureModelsState> => {
  const response = await api.post<BackendTextureModelsState>(
    '/api/ai/texture-plan/refresh-review',
    {
      session_id: payload.sessionId,
      result_id: payload.resultId ?? null,
    },
    {
      ...authHeader(token),
      timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
    }
  );
  return mapBackendTextureModelsState(response.data);
};

export const startGenerateModelTextures = async (
  token: string,
  payload: {
    sessionId: number;
    sourceText?: string;
    documentFile?: File | null;
    referenceImageFile?: File | null;
    selectedImageKeywords?: string[];
  },
): Promise<{ sessionId: number; status: string }> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  if (payload.sourceText && payload.sourceText.trim().length > 0) {
    formData.append('source_text', payload.sourceText);
  }
  if (payload.documentFile) {
    formData.append('document', payload.documentFile);
  }
  if (payload.referenceImageFile) {
    formData.append('reference_image', payload.referenceImageFile);
  }
  if (payload.selectedImageKeywords) {
    formData.append('selected_image_keywords_json', JSON.stringify(payload.selectedImageKeywords));
  }

  const response = await api.post<{ session_id: number; status: string }>(
    '/api/ai/texture-plan/generate-model-textures',
    formData,
    {
      ...authHeader(token),
      headers: {
        ...authHeader(token).headers,
        'Content-Type': 'multipart/form-data',
      },
      timeout: 30000,
    },
  );
  return {
    sessionId: response.data.session_id,
    status: response.data.status,
  };
};

export const applyEditedTexture = async (
  token: string,
  payload: {
    sessionId: number;
    resultId: string;
    editedBaseColorFile: File;
  },
): Promise<TextureModelsState> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  formData.append('result_id', payload.resultId);
  formData.append('edited_base_color', payload.editedBaseColorFile);

  const response = await api.post<BackendTextureModelsState>('/api/ai/texture-plan/apply-edited-texture', formData, {
    ...authHeader(token),
    headers: {
      ...authHeader(token).headers,
      'Content-Type': 'multipart/form-data',
    },
    timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
  });
  return mapBackendTextureModelsState(response.data);
};

export const uploadCustomTexturedModel = async (
  token: string,
  payload: {
    sessionId: number;
    modelFile: File;
    baseColorFile: File;
    title?: string;
  },
): Promise<TextureModelsState> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  formData.append('model_file', payload.modelFile);
  formData.append('base_color_file', payload.baseColorFile);
  if (payload.title && payload.title.trim().length > 0) {
    formData.append('title', payload.title.trim());
  }

  const response = await api.post<BackendTextureModelsState>('/api/ai/texture-plan/upload-textured-model', formData, {
    ...authHeader(token),
    headers: {
      ...authHeader(token).headers,
      'Content-Type': 'multipart/form-data',
    },
    timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
  });
  return mapBackendTextureModelsState(response.data);
};

export const parseBrief = async (
  token: string,
  payload: ParseBriefPayload,
): Promise<{ sessionId: number; stage: SessionStage; brief: DesignBrief }> => {
  const response = await api.post<{
    session_id: number;
    stage: SessionStage;
    brief_json: DesignBrief;
  }>(
    '/api/ai/parse-brief',
    {
      session_id: payload.sessionId,
      design_goal: payload.designGoal,
      product_category: payload.productCategory,
    },
    authHeader(token),
  );

  return {
    sessionId: response.data.session_id,
    stage: response.data.stage,
    brief: response.data.brief_json,
  };
};

export const generateAiImage = async (
  token: string,
  payload: {
    sessionId: number;
    prompt: string;
    styleHint?: string;
    referenceImages?: string[];
  },
): Promise<GeneratedPatternImage[]> => {
  const response = await api.post<{ items: BackendGeneratedImage[] }>(
    '/api/ai/generate-image',
    {
      session_id: payload.sessionId,
      prompt: payload.prompt,
      style_hint: payload.styleHint ?? null,
      reference_images: payload.referenceImages ?? [],
    },
    {
      ...authHeader(token),
      timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
    },
  );
  return response.data.items.map(mapBackendGeneratedImage);
};

export const generateTexturePattern = async (
  token: string,
  payload: {
    sessionId: number;
    resultId: string;
    previewMode: 'meshy' | 'edited';
    workspaceId: string;
    patternPromptText?: string;
    canvasSnapshotDataUrl?: string | null;
  },
): Promise<GeneratedPatternPreview> => {
  const response = await api.post<BackendTexturePatternGenerateResponse>(
    '/api/ai/texture-plan/generate-pattern',
    {
      session_id: payload.sessionId,
      result_id: payload.resultId,
      preview_mode: payload.previewMode,
      workspace_id: payload.workspaceId,
      pattern_prompt_text: payload.patternPromptText?.trim() || null,
      canvas_snapshot_data_url: payload.canvasSnapshotDataUrl ?? null,
    },
    {
      ...authHeader(token),
      timeout: AI_IMAGE_REQUEST_TIMEOUT_MS,
    },
  );
  return {
    item: mapBackendGeneratedImage(response.data.item),
    analysisSummary: response.data.analysis_summary,
    dominantColors: response.data.dominant_colors ?? [],
    sourceResultId: response.data.source_result_id,
    patternPromptText: response.data.pattern_prompt_text ?? null,
  };
};

export const generateStage4SceneImage = async (
  token: string,
  payload: {
    sessionId: number;
    resultId?: string | null;
    schemeName?: string | null;
    screenshotDataUrl: string;
    imagePrompt: string;
  },
): Promise<Stage4SceneImageResult> => {
  const response = await api.post<BackendStage4SceneImageResponse>(
    '/api/ai/stage4/scene-image',
    {
      session_id: payload.sessionId,
      result_id: payload.resultId ?? null,
      scheme_name: payload.schemeName ?? null,
      screenshot_data_url: payload.screenshotDataUrl,
      image_prompt: payload.imagePrompt,
    },
    {
      ...authHeader(token),
      timeout: STAGE4_MEDIA_REQUEST_TIMEOUT_MS,
    },
  );
  return {
    sessionId: response.data.session_id,
    resultId: response.data.result_id,
    imageUrl: mapMediaUrl(response.data.image_url),
    imagePredictionId: response.data.image_prediction_id,
    imagePrompt: response.data.image_prompt,
    createdImage: response.data.created_image ? mapBackendGeneratedImage(response.data.created_image) : null,
    mediaAsset: response.data.media_asset ? mapBackendGeneratedMediaAsset(response.data.media_asset) : null,
  };
};

export const fetchStage4Media = async (
  token: string,
  payload: { sessionId: number; resultId?: string | null },
): Promise<Stage4MediaAsset[]> => {
  const response = await api.get<{ items: BackendGeneratedMediaAsset[] }>('/api/ai/stage4/media', {
    ...authHeader(token),
    params: {
      session_id: payload.sessionId,
      result_id: payload.resultId ?? undefined,
    },
  });
  return (response.data.items ?? []).map(mapBackendGeneratedMediaAsset);
};

export const generateSceneRenderImage = generateStage4SceneImage;

export const fetchSceneRenderMedia = fetchStage4Media;

export const deleteStage4Media = async (
  token: string,
  payload: { sessionId: number; assetId: number },
): Promise<void> => {
  await api.delete(`/api/ai/stage4/media/${payload.assetId}`, {
    ...authHeader(token),
    params: {
      session_id: payload.sessionId,
    },
  });
};

export const generateStage4SceneVideo = async (
  token: string,
  payload: {
    sessionId: number;
    resultId?: string | null;
    schemeName?: string | null;
    imageUrl: string;
    videoPrompt: string;
    duration?: number;
    resolution?: '480p' | '720p' | '1080p' | '1080p-SR' | '1440p-SR';
    generateAudio?: boolean;
  },
): Promise<Stage4SceneVideoResult> => {
  const response = await api.post<BackendStage4SceneVideoResponse>(
    '/api/ai/stage4/scene-video',
    {
      session_id: payload.sessionId,
      result_id: payload.resultId ?? null,
      scheme_name: payload.schemeName ?? null,
      image_url: payload.imageUrl,
      video_prompt: payload.videoPrompt,
      duration: payload.duration ?? 5,
      resolution: payload.resolution ?? '480p',
      generate_audio: payload.generateAudio ?? true,
    },
    {
      ...authHeader(token),
      timeout: STAGE4_MEDIA_REQUEST_TIMEOUT_MS,
    },
  );
  return {
    sessionId: response.data.session_id,
    resultId: response.data.result_id,
    videoUrl: mapMediaUrl(response.data.video_url),
    videoPredictionId: response.data.video_prediction_id,
    videoPrompt: response.data.video_prompt,
    mediaAsset: response.data.media_asset ? mapBackendGeneratedMediaAsset(response.data.media_asset) : null,
  };
};

export const uploadModel = async (
  token: string,
  sessionId: number,
  productCategory: ProductCategory,
  file: File,
): Promise<{ taskId: number; status: string; progress: number; pipelineStage: string | null }> => {
  const formData = new FormData();
  formData.append('session_id', String(sessionId));
  formData.append('product_category', productCategory);
  formData.append('file', file);

  const response = await api.post<{
    task_id: number;
    status: string;
    progress: number;
    pipeline_stage: string | null;
  }>('/api/models/upload', formData, {
    ...authHeader(token),
    headers: {
      ...authHeader(token).headers,
      'Content-Type': 'multipart/form-data',
    },
  });

  return {
    taskId: response.data.task_id,
    status: response.data.status,
    progress: response.data.progress,
    pipelineStage: response.data.pipeline_stage,
  };
};

export const fetchModelLibrary = async (token: string): Promise<ModelLibraryItem[]> => {
  const response = await api.get<{ items: BackendModelAsset[] }>('/api/models/library', authHeader(token));
  return response.data.items.map((item) => ({
    id: item.id,
    name: item.name,
    baseModel: mapBackendModelAsset(item),
  }));
};

export const generateModel = async (
  token: string,
  payload: { sessionId: number; productCategory: ProductCategory; productProfile: ProductProfile },
): Promise<{ taskId: number; status: string; progress: number }> => {
  const response = await api.post<{ task_id: number; status: string; progress: number }>(
    '/api/models/generate',
    {
      session_id: payload.sessionId,
      product_category: payload.productCategory,
      product_profile: payload.productProfile,
    },
    authHeader(token),
  );

  return {
    taskId: response.data.task_id,
    status: response.data.status,
    progress: response.data.progress,
  };
};

export const fetchModelTask = async (
  token: string,
  taskId: number,
): Promise<{
  taskId: number;
  sessionId: number;
  status: string;
  progress: number;
  pipelineStage: string | null;
  progressMessage: string | null;
  errorMessage?: string;
  resultModel: BaseModelMeta | null;
}> => {
  const response = await api.get<{
    task_id: number;
    session_id: number;
    status: string;
    progress: number;
    pipeline_stage?: string | null;
    progress_message?: string | null;
    error_message?: string;
    result_model?: BackendModelAsset;
  }>(`/api/models/tasks/${taskId}`, authHeader(token));

  return {
    taskId: response.data.task_id,
    sessionId: response.data.session_id,
    status: response.data.status,
    progress: response.data.progress,
    pipelineStage: response.data.pipeline_stage ?? null,
    progressMessage: response.data.progress_message ?? null,
    errorMessage: response.data.error_message,
    resultModel: response.data.result_model ? mapBackendModelAsset(response.data.result_model) : null,
  };
};

export const selectBaseModel = async (
  token: string,
  sessionId: number,
  baseModelId: number,
): Promise<{ sessionId: number; baseModelId: number | null; modelLockedAt: string | null }> => {
  const response = await api.post<{ session_id: number; base_model_id: number | null; model_locked_at: string | null }>(
    `/api/sessions/${sessionId}/base-model/select`,
    { base_model_id: baseModelId },
    authHeader(token),
  );

  return {
    sessionId: response.data.session_id,
    baseModelId: response.data.base_model_id,
    modelLockedAt: response.data.model_locked_at,
  };
};

export const fetchSessionBaseModel = async (
  token: string,
  sessionId: number,
): Promise<{ baseModelId: number | null; modelLockedAt: string | null; baseModel: BaseModelMeta | null }> => {
  const response = await api.get<{
    session_id: number;
    base_model_id: number | null;
    model_locked_at: string | null;
    base_model: BackendModelAsset | null;
  }>(`/api/sessions/${sessionId}/base-model`, authHeader(token));

  return {
    baseModelId: response.data.base_model_id,
    modelLockedAt: response.data.model_locked_at,
    baseModel: response.data.base_model
      ? mapBackendModelAsset(response.data.base_model, response.data.model_locked_at)
      : null,
  };
};

export const getApiBaseUrl = (): string => API_BASE_URL;

export const parseApiError = (error: unknown, fallbackMessage: string): string => {
  const detailTextMap: Record<string, string> = {
    'Invite code not found': '协作空间口令不存在',
    'Session not found': '协作空间不存在',
  };

  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detailTextMap[detail.trim()] ?? detail;
    }
    if (!error.response) {
      const reason = error.code === 'ECONNABORTED' ? 'Request timed out' : 'Could not connect to backend service';
      return `${reason}: ${API_BASE_URL}`;
    }
    if (typeof error.message === 'string' && error.message.trim().length > 0) {
      return error.message;
    }
  }
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return fallbackMessage;
};
