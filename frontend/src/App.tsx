import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Brush,
  Circle,
  Copy,
  Eraser,
  ImagePlus,
  LogIn,
  LogOut,
  LoaderCircle,
  Mic,
  MicOff,
  MousePointer2,
  PenTool,
  RectangleHorizontal,
  Save,
  Settings2,
  Slash,
  Sparkles,
  Video,
  VideoOff,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import AppErrorBoundary from './components/AppErrorBoundary.tsx';
import DesignerCanvas, { type DesignerCanvasHandle } from './components/DesignerCanvas.tsx';
import MeetingSettingsModal from './components/MeetingSettingsModal.tsx';
import ParticipantSidebar from './components/ParticipantSidebar.tsx';
import PreJoinPanel from './components/PreJoinPanel.tsx';
import Stage2LinkedPreview from './components/Stage2LinkedPreview.tsx';
import TexturePlanningSidebar from './components/TexturePlanningSidebar.tsx';
import { Stage1PlanningView, Stage3ReviewView, Stage4PreviewView } from './components/stages/index.ts';
import { useMeetingRtc } from './hooks/useMeetingRtc.ts';
import {
  advanceSessionStage,
  analyzeTexturePlanImage,
  ensureUserToken,
  fetchModelTask,
  fetchSessionMembers,
  fetchSessionBaseModel,
  fetchSessionDetail,
  fetchSessionSettings,
  fetchSharedTextureResults,
  fetchStage3SharedTextureModels,
  applyEditedTexture,
  deleteTextureModel,
  fetchTextureModels,
  fetchTexturePlan,
  generateTexturePattern,
  getApiBaseUrl,
  importSharedTextureResults,
  joinSessionByInvite,
  patchTexturePlan,
  patchSessionSettings,
  parseApiError,
  parseBrief,
  refreshTextureModelReview,
  revertSessionStage,
  selectBaseModel,
  shareTextureResults,
  startGenerateModelTextures,
  type GeneratedPatternPreview,
  uploadCustomTexturedModel,
  uploadModel,
} from './services/apiClient.ts';
import type {
  BaseModelMeta,
  BaseModelSource,
  CanvasTool,
  DesignBrief,
  ProductCategory,
  ProductProfile,
  ReviewScheme,
  TexturedModel,
  TextureModelsState,
  TexturePlanState,
  UvFocusPoint,
} from './types/design.ts';
import type {
  AuthUser,
  MeetingRole,
  MeetingSettings,
  MeetingSettingsPermissions,
  MeetingSettingsSection,
  MeetingSettingsSectionId,
  PreJoinSettings,
  PeerMediaState,
  ReviewPersonaRoleConfig,
  SessionMemberDirectoryEntry,
  SessionStage,
} from './types/meeting.ts';
import { buildReviewSchemes } from './utils/reviewScoring.ts';

type AppScreen = 'entry' | 'prejoin' | 'meeting';
type UiStage = 1 | 2 | 3 | 4;
type TexturePreviewMode = 'meshy' | 'edited';
type Stage2ReviewRole = 'engineering' | 'passenger';
type PersistedTextureWorkspaceState = {
  selectedTexturedResultId: string | null;
  activeTextureWorkspaceId: string;
  previewModeByResultId: Record<string, TexturePreviewMode>;
  selectedTexturedSchemeId?: string | null;
  previewModeByScheme?: Record<string, TexturePreviewMode>;
  canvasTextureLayer: {
    workspaceId: string;
    imageUrl: string;
    label?: string;
  } | null;
};

const DEFAULT_PASSWORD = 'CoTrack@123456';
const DEFAULT_DESIGN_GOAL = '';
const DEFAULT_PRODUCT_CATEGORY: ProductCategory = 'high_speed_train';
const DEFAULT_PRODUCT_PROFILE: ProductProfile = {
  series: 'CR400AF',
  formation: '8 编组',
  totalLengthM: 208.95,
  maxWidthMm: 3360,
  maxHeightMm: 3700,
};
const DEFAULT_STAGE2_COMMENT_PANEL_STATE: Record<
  Stage2ReviewRole,
  { open: boolean; loading: boolean; error: string | null }
> = {
  engineering: { open: false, loading: false, error: null },
  passenger: { open: false, loading: false, error: null },
};
const AGENT_MEMBER_IDS: Record<Stage2ReviewRole, number> = {
  engineering: -101,
  passenger: -102,
};
const DEFAULT_MEETING_SETTINGS: MeetingSettings = {
  revision: 1,
  updatedAt: null,
  updatedByUserId: null,
  reviewPersonas: {
    passenger: {
      displayName: '普通乘客',
      identitySummary:
        '从第一印象、舒适度、信任感和乘坐意愿判断方案的普通高铁乘客。',
      preferenceTags: ['干净', '可靠', '现代', '舒适'],
      dislikeTags: ['图形杂乱', '对比刺眼', '质感廉价'],
      focusPoints: ['第一印象', '安全信任', '舒适整洁', '品质感'],
    },
    engineering: {
      displayName: '涂装工艺工程师',
      identitySummary:
        '从可制造性、遮蔽工序、耐久性和全周期成本评估外观涂装的工程角色。',
      priorityTags: ['工艺稳定', '涂层耐久', '色区可控', '易维护'],
      riskFocus: ['色差风险', '渐变复杂度', '遮蔽工作量', '维护周期'],
      focusPoints: ['油漆用量', '工艺步骤', '成本', '耐久性', '曲面贴合'],
    },
    roles: [
      {
        id: 'passenger_default',
        type: 'passenger',
        enabled: true,
        displayName: '普通乘客',
        identitySummary: '从第一印象、舒适度、信任感和乘坐意愿判断方案的普通高铁乘客。',
        preferenceTags: ['干净', '可靠', '现代', '舒适'],
        dislikeTags: ['图形杂乱', '对比刺眼', '质感廉价'],
        priorityTags: [],
        riskFocus: [],
        focusPoints: ['第一印象', '安全信任', '舒适整洁', '品质感'],
      },
      {
        id: 'engineering_default',
        type: 'engineering',
        enabled: true,
        displayName: '涂装工艺工程师',
        identitySummary: '从可制造性、遮蔽工序、耐久性和全周期成本评估外观涂装的工程角色。',
        preferenceTags: [],
        dislikeTags: [],
        priorityTags: ['工艺稳定', '涂层耐久', '色区可控', '易维护'],
        riskFocus: ['色差风险', '渐变复杂度', '遮蔽工作量', '维护周期'],
        focusPoints: ['油漆用量', '工艺步骤', '成本', '耐久性', '曲面贴合'],
      },
    ],
  },
};
const DISPLAY_NAME_STORAGE_KEY = 'co-track:display-name';
const INVITE_CODE_STORAGE_KEY = 'co-track:invite-code';
const ROLE_STORAGE_KEY = 'co-track:selected-role';
const TAB_IDENTITY_STORAGE_KEY = 'co-track:tab-user-seed';

const HEADER_STAGE_LABELS: Record<UiStage, string> = {
  1: 'S1 目标',
  2: 'S2 画布',
  3: 'S3 评审',
  4: 'S4 预览',
};
const STAGE_ORDER: UiStage[] = [1, 2, 3, 4];

const TOOL_OPTIONS: Array<{ id: CanvasTool; label: string; icon: React.ReactNode }> = [
  { id: 'select', label: '选择', icon: <MousePointer2 size={14} /> },
  { id: 'pencil', label: '画笔', icon: <PenTool size={14} /> },
  { id: 'rect', label: '矩形', icon: <RectangleHorizontal size={14} /> },
  { id: 'ellipse', label: '椭圆', icon: <Circle size={14} /> },
  { id: 'line', label: '线条', icon: <Slash size={14} /> },
  { id: 'eraser', label: '橡皮', icon: <Eraser size={14} /> },
];

const mapBackendStageToUiStage = (stage: SessionStage): UiStage => {
  if (stage === 'DESIGNING') {
    return 2;
  }
  if (stage === 'COLLECTING' || stage === 'REVIEWING') {
    return 3;
  }
  if (stage === 'PREVIEWING') {
    return 4;
  }
  return 1;
};

const delay = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));

const getTextureWorkspaceId = (
  baseModelId: number | null,
  model: Pick<TexturedModel, 'resultId' | 'meshyTaskId'> | null,
): string => {
  const safeBaseModelId = baseModelId ?? 'no-model';
  if (!model) {
    return `workspace:${safeBaseModelId}:base`;
  }
  const stableToken = model.meshyTaskId || model.resultId;
  return `workspace:${safeBaseModelId}:${stableToken}`;
};

const readStoredText = (storageKey: string, fallback: string): string => {
  if (typeof window === 'undefined') {
    return fallback;
  }
  const stored = window.sessionStorage.getItem(storageKey);
  return stored && stored.trim().length > 0 ? stored : fallback;
};

const ensureTabIdentitySeed = (): string => {
  if (typeof window === 'undefined') {
    return 'tab-server';
  }
  const existing = window.sessionStorage.getItem(TAB_IDENTITY_STORAGE_KEY);
  if (existing && existing.trim().length > 0) {
    return existing;
  }
  const generated =
    typeof window.crypto?.randomUUID === 'function'
      ? window.crypto.randomUUID()
      : `tab_${Date.now()}_${Math.round(Math.random() * 1_000_000)}`;
  window.sessionStorage.setItem(TAB_IDENTITY_STORAGE_KEY, generated);
  return generated;
};

const getTextureWorkspaceStorageKey = (
  sessionId: number | null,
  baseModelId: number | null,
  userKey: string | number | null,
): string => `co-track:texture-ui:${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}:${userKey ?? 'anon'}`;

const getCanvasSnapshotStorageKey = (
  sessionId: number | null,
  baseModelId: number | null,
  userKey: string | number | null,
  resultId: string,
): string => `co-track:snapshot:${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}:${userKey ?? 'anon'}:${resultId}`;

const getReviewStarStorageKey = (sessionId: number | null, userKey: string | number | null): string =>
  `co-track:review-stars:${sessionId ?? 'no-session'}:${userKey ?? 'anon'}`;

const cloneDefaultProductProfile = (): ProductProfile => ({ ...DEFAULT_PRODUCT_PROFILE });

const isEditableEventTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const tagName = target.tagName.toLowerCase();
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select';
};

const getStage2QuickComment = (
  model: TexturedModel | null | undefined,
  role: Stage2ReviewRole,
): string | null => {
  if (!model?.reviewAssessment || model.reviewAssessment.status !== 'completed') {
    return null;
  }
  if (role === 'engineering') {
    return model.reviewAssessment.engineering?.quickComment ?? null;
  }
  return model.reviewAssessment.passenger?.quickComment ?? null;
};

const cloneReviewRole = (role: ReviewPersonaRoleConfig): ReviewPersonaRoleConfig => ({
  ...role,
  focusPoints: [...role.focusPoints],
  preferenceTags: [...role.preferenceTags],
  dislikeTags: [...role.dislikeTags],
  priorityTags: [...role.priorityTags],
  riskFocus: [...role.riskFocus],
});

const cloneMeetingSettings = (value: MeetingSettings | null | undefined = DEFAULT_MEETING_SETTINGS): MeetingSettings => ({
  revision: value?.revision ?? DEFAULT_MEETING_SETTINGS.revision,
  updatedAt: value?.updatedAt ?? DEFAULT_MEETING_SETTINGS.updatedAt,
  updatedByUserId: value?.updatedByUserId ?? DEFAULT_MEETING_SETTINGS.updatedByUserId,
  reviewPersonas: {
    passenger: {
      displayName: value?.reviewPersonas.passenger.displayName ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.passenger.displayName,
      identitySummary:
        value?.reviewPersonas.passenger.identitySummary ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.passenger.identitySummary,
      preferenceTags: [...(value?.reviewPersonas.passenger.preferenceTags ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.passenger.preferenceTags)],
      dislikeTags: [...(value?.reviewPersonas.passenger.dislikeTags ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.passenger.dislikeTags)],
      focusPoints: [...(value?.reviewPersonas.passenger.focusPoints ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.passenger.focusPoints)],
    },
    engineering: {
      displayName:
        value?.reviewPersonas.engineering.displayName ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.engineering.displayName,
      identitySummary:
        value?.reviewPersonas.engineering.identitySummary ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.engineering.identitySummary,
      priorityTags: [...(value?.reviewPersonas.engineering.priorityTags ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.engineering.priorityTags)],
      riskFocus: [...(value?.reviewPersonas.engineering.riskFocus ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.engineering.riskFocus)],
      focusPoints: [...(value?.reviewPersonas.engineering.focusPoints ?? DEFAULT_MEETING_SETTINGS.reviewPersonas.engineering.focusPoints)],
    },
    roles: (value?.reviewPersonas.roles?.length
      ? value.reviewPersonas.roles
      : DEFAULT_MEETING_SETTINGS.reviewPersonas.roles).map(cloneReviewRole),
  },
});

const RemoteAudioSink: React.FC<{ peer: PeerMediaState; listeningEnabled: boolean }> = ({ peer, listeningEnabled }) => {
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }

    audio.srcObject = peer.stream ?? null;
    audio.muted = !listeningEnabled || !peer.audioEnabled;

    if (peer.stream && listeningEnabled && peer.audioEnabled) {
      void audio.play().catch(() => undefined);
    }

    return () => {
      audio.srcObject = null;
    };
  }, [listeningEnabled, peer.audioEnabled, peer.stream]);

  return (
    <audio
      ref={audioRef}
      autoPlay
      muted={!listeningEnabled || !peer.audioEnabled}
      aria-label={`${peer.name} 的声音`}
      className="hidden"
    />
  );
};

const normalizeProductProfile = (value: unknown): ProductProfile => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return cloneDefaultProductProfile();
  }

  const normalized: ProductProfile = {};
  for (const [key, rawValue] of Object.entries(value)) {
    if (typeof rawValue === 'string' || typeof rawValue === 'number' || typeof rawValue === 'boolean') {
      normalized[key] = rawValue;
    }
  }

  return Object.keys(normalized).length > 0 ? normalized : cloneDefaultProductProfile();
};

const clearSessionWorkspaceCache = (sessionId: number | null, userKey: string | number | null) => {
  if (typeof window === 'undefined' || !sessionId) {
    return;
  }
  const reviewPrefix = `co-track:review-stars:${sessionId}:${userKey ?? 'anon'}`;
  const keysToDelete: string[] = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const storageKey = window.localStorage.key(index);
    if (!storageKey) {
      continue;
    }
    if (
      storageKey.startsWith(`co-track:texture-ui:${sessionId}:`) &&
      storageKey.endsWith(`:${userKey ?? 'anon'}`)
    ) {
      keysToDelete.push(storageKey);
      continue;
    }
    if (
      storageKey.startsWith(`co-track:snapshot:${sessionId}:`) &&
      storageKey.includes(`:${userKey ?? 'anon'}:`)
    ) {
      keysToDelete.push(storageKey);
      continue;
    }
    if (storageKey.startsWith(reviewPrefix)) {
      keysToDelete.push(storageKey);
    }
  }
  keysToDelete.forEach((storageKey) => window.localStorage.removeItem(storageKey));
};

const readPersistedReviewStars = (
  sessionId: number | null,
  userKey: string | number | null,
): Record<string, string[]> => {
  if (typeof window === 'undefined' || !sessionId) {
    return {};
  }
  const raw = window.localStorage.getItem(getReviewStarStorageKey(sessionId, userKey));
  if (!raw) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([schemeId, value]) => {
        if (!Array.isArray(value)) {
          return [];
        }
        const userIds = value.filter((item): item is string => typeof item === 'string' && item.length > 0);
        return [[schemeId, Array.from(new Set(userIds))]];
      }),
    );
  } catch {
    return {};
  }
};

const readPersistedTextureWorkspaceState = (
  sessionId: number | null,
  baseModelId: number | null,
  userKey: string | number | null,
): PersistedTextureWorkspaceState | null => {
  if (typeof window === 'undefined' || !sessionId) {
    return null;
  }
  const raw = window.localStorage.getItem(getTextureWorkspaceStorageKey(sessionId, baseModelId, userKey));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedTextureWorkspaceState> | null;
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }

    const rawPreviewModes =
      (parsed.previewModeByResultId && typeof parsed.previewModeByResultId === 'object'
        ? parsed.previewModeByResultId
        : parsed.previewModeByScheme) ?? {};

    const previewModeByResultId = Object.fromEntries(
      Object.entries(rawPreviewModes).filter(
        ([resultId, mode]) =>
          typeof resultId === 'string' && resultId.length > 0 && (mode === 'meshy' || mode === 'edited'),
      ),
    ) as Record<string, TexturePreviewMode>;

    const canvasTextureLayer =
      parsed.canvasTextureLayer &&
      typeof parsed.canvasTextureLayer.workspaceId === 'string' &&
      typeof parsed.canvasTextureLayer.imageUrl === 'string'
        ? {
            workspaceId: parsed.canvasTextureLayer.workspaceId,
            imageUrl: parsed.canvasTextureLayer.imageUrl,
            label:
              typeof parsed.canvasTextureLayer.label === 'string' ? parsed.canvasTextureLayer.label : undefined,
          }
        : null;

    return {
      selectedTexturedResultId:
        typeof parsed.selectedTexturedResultId === 'string' || parsed.selectedTexturedResultId === null
          ? parsed.selectedTexturedResultId
          : typeof parsed.selectedTexturedSchemeId === 'string' || parsed.selectedTexturedSchemeId === null
            ? parsed.selectedTexturedSchemeId
          : null,
      activeTextureWorkspaceId:
        typeof parsed.activeTextureWorkspaceId === 'string' && parsed.activeTextureWorkspaceId.length > 0
          ? parsed.activeTextureWorkspaceId
          : getTextureWorkspaceId(baseModelId, null),
      previewModeByResultId,
      canvasTextureLayer,
    };
  } catch {
    return null;
  }
};

const toPngFileFromDataUrl = (dataUrl: string, fileName: string): File => {
  const [header, body] = dataUrl.split(',', 2);
  if (!header || !body) {
    throw new Error('画布导出未返回有效的 PNG 数据。');
  }
  const mimeMatch = header.match(/^data:(.*?);base64$/i);
  const mimeType = mimeMatch?.[1] ?? 'image/png';
  const binary = window.atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new File([bytes], fileName, { type: mimeType });
};

type SocketModelPayload = {
  id: number;
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

const toAbsoluteResourceUrl = (value: string): string => {
  if (/^https?:\/\//i.test(value)) {
    return value;
  }
  const apiBaseUrl = getApiBaseUrl();
  const normalizedBase = apiBaseUrl.endsWith('/') ? apiBaseUrl : `${apiBaseUrl}/`;
  const normalizedPath = value.startsWith('/') ? value.slice(1) : value;
  return new URL(normalizedPath, normalizedBase).toString();
};

const toBaseModelFromSocket = (payload: SocketModelPayload, lockedAt?: string | null): BaseModelMeta => ({
  baseModelId: Math.round(toSafeNumber(payload.id)),
  sourceType: payload.source_type,
  precisionLevel: payload.precision_level,
  modelUrl: toAbsoluteResourceUrl(payload.model_url),
  uvTemplateUrl: toAbsoluteResourceUrl(payload.uv_template_url),
  surfaceAreaM2: toSafeNumber(payload.surface_area_m2),
  paintableUvPixels: Math.round(toSafeNumber(payload.paintable_uv_pixels)),
  exportGlbAllowed: payload.export_glb_allowed,
  licenseScope: payload.license_scope,
  lockedAt: lockedAt ?? undefined,
  mappingMeta: payload.mapping_meta
    ? {
        inspection: payload.mapping_meta.inspection
          ? {
              fileName: payload.mapping_meta.inspection.file_name,
              format: payload.mapping_meta.inspection.format,
              meshCount: payload.mapping_meta.inspection.mesh_count,
              materialCount: payload.mapping_meta.inspection.material_count,
              bboxM: payload.mapping_meta.inspection.bbox_m,
              hasOriginalUv: payload.mapping_meta.inspection.has_original_uv,
              uvSource: payload.mapping_meta.inspection.uv_source,
              uvTemplateMode: payload.mapping_meta.inspection.uv_template_mode,
              warnings: payload.mapping_meta.inspection.warnings,
            }
          : undefined,
        uvSpec: payload.mapping_meta.uv_spec
          ? {
              width: payload.mapping_meta.uv_spec.width,
              height: payload.mapping_meta.uv_spec.height,
              paintableUvPixels: payload.mapping_meta.uv_spec.paintable_uv_pixels,
            }
          : undefined,
        meshToRegion: payload.mapping_meta.mesh_to_region,
      }
    : undefined,
});

const App: React.FC = () => {
  const [screen, setScreen] = useState<AppScreen>('entry');
  const [tabIdentitySeed] = useState(() => ensureTabIdentitySeed());
  const [displayName, setDisplayName] = useState(() => readStoredText(DISPLAY_NAME_STORAGE_KEY, '设计师 A'));
  const [inviteCode, setInviteCode] = useState(() => readStoredText(INVITE_CODE_STORAGE_KEY, '555555'));
  const [selectedRole, setSelectedRole] = useState<MeetingRole>(
    () => (readStoredText(ROLE_STORAGE_KEY, 'designer') as MeetingRole) || 'designer',
  );
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  const [token, setToken] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessionName, setSessionName] = useState<string>('');
  const [backendStage, setBackendStage] = useState<SessionStage>('LOBBY');
  const [meetingRole, setMeetingRole] = useState<MeetingRole>('designer');
  const [listeningEnabled, setListeningEnabled] = useState(true);

  const [uiStage, setUiStage] = useState<UiStage>(1);
  const [stageAdvancing, setStageAdvancing] = useState(false);
  const [stageReverting, setStageReverting] = useState(false);
  const [preJoinSettings, setPreJoinSettings] = useState<PreJoinSettings | null>(null);

  const [designGoal, setDesignGoal] = useState(DEFAULT_DESIGN_GOAL);
  const [productCategory, setProductCategory] = useState<ProductCategory>(DEFAULT_PRODUCT_CATEGORY);
  const [modelSource, setModelSource] = useState<BaseModelSource>('upload');
  const [productProfile, setProductProfile] = useState<ProductProfile>(() => cloneDefaultProductProfile());
  const [brief, setBrief] = useState<DesignBrief | null>(null);
  const [baseModel, setBaseModel] = useState<BaseModelMeta | null>(null);
  const [baseModelLocked, setBaseModelLocked] = useState(false);
  const [uploadedModelFile, setUploadedModelFile] = useState<File | null>(null);
  const [modelPreparing, setModelPreparing] = useState(false);
  const [modelTaskStatus, setModelTaskStatus] = useState<string | null>(null);
  const [modelTaskProgress, setModelTaskProgress] = useState(0);
  const [modelPipelineStage, setModelPipelineStage] = useState<string | null>(null);
  const [modelProgressMessage, setModelProgressMessage] = useState<string | null>(null);
  const [texturePlan, setTexturePlan] = useState<TexturePlanState | null>(null);
  const [texturePlanLoading, setTexturePlanLoading] = useState(false);
  const [texturePlanGenerating, setTexturePlanGenerating] = useState(false);
  const [texturePlanSaving, setTexturePlanSaving] = useState(false);
  const [textureImageAnalyzing, setTextureImageAnalyzing] = useState(false);

  const [tool, setTool] = useState<CanvasTool>('pencil');
  const [strokeColor, setStrokeColor] = useState('#0f172a');
  const [fillColor, setFillColor] = useState('#38bdf8');
  const [lastAutoSavedAt, setLastAutoSavedAt] = useState<string>('');
  const [linkedUvFocus, setLinkedUvFocus] = useState<UvFocusPoint | null>(null);
  const [texturedModels, setTexturedModels] = useState<TexturedModel[]>([]);
  const [textureModelsStatus, setTextureModelsStatus] = useState<TextureModelsState['status']>('idle');
  const [meetingSharedReviewModels, setMeetingSharedReviewModels] = useState<TexturedModel[]>([]);
  const [selectedTexturedResultId, setSelectedTexturedResultId] = useState<string | null>(null);
  const [activeTextureWorkspaceId, setActiveTextureWorkspaceId] = useState<string>('workspace:no-model:base');
  const [previewModeByResultId, setPreviewModeByResultId] = useState<Record<string, TexturePreviewMode>>({});
  const [applyTexturePending, setApplyTexturePending] = useState(false);
  const [deletingTexturedResultId, setDeletingTexturedResultId] = useState<string | null>(null);
  const [refreshReviewPendingResultId, setRefreshReviewPendingResultId] = useState<string | null>(null);
  const [stage2CommentPanels, setStage2CommentPanels] = useState(DEFAULT_STAGE2_COMMENT_PANEL_STATE);
  const [workspaceHasContent, setWorkspaceHasContent] = useState<Record<string, boolean>>({});
  const [canvasInsertAsset, setCanvasInsertAsset] = useState<{
    requestId: number;
    imageUrl: string;
    label?: string;
  } | null>(null);
  const [patternPopoverOpen, setPatternPopoverOpen] = useState(false);
  const [patternPromptText, setPatternPromptText] = useState('');
  const [patternGenerating, setPatternGenerating] = useState(false);
  const [patternPreviewItem, setPatternPreviewItem] = useState<GeneratedPatternPreview | null>(null);
  const [canvasHasSelection, setCanvasHasSelection] = useState(false);
  const [canvasTextureLayer, setCanvasTextureLayer] = useState<{
    requestId: number;
    workspaceId: string;
    imageUrl: string;
    label?: string;
  } | null>(null);
  const [starredSchemes, setStarredSchemes] = useState<Record<string, string[]>>({});
  const [sessionMembers, setSessionMembers] = useState<SessionMemberDirectoryEntry[]>([]);
  const [meetingSettings, setMeetingSettings] = useState<MeetingSettings | null>(null);
  const [meetingSettingsPermissions, setMeetingSettingsPermissions] = useState<MeetingSettingsPermissions | null>(null);
  const [meetingSettingsSections, setMeetingSettingsSections] = useState<MeetingSettingsSection[]>([]);
  const [meetingSettingsOpen, setMeetingSettingsOpen] = useState(false);
  const [meetingSettingsLoading, setMeetingSettingsLoading] = useState(false);
  const [meetingSettingsSaving, setMeetingSettingsSaving] = useState(false);
  const [activeMeetingSettingsSection, setActiveMeetingSettingsSection] =
    useState<MeetingSettingsSectionId>('review_roles');
  const [sharingResultsPending, setSharingResultsPending] = useState(false);
  const [sharedResultsViewerOpen, setSharedResultsViewerOpen] = useState(false);
  const [sharedResultsViewerLoading, setSharedResultsViewerLoading] = useState(false);
  const [sharedResultsViewerImporting, setSharedResultsViewerImporting] = useState(false);
  const [sharedResultsViewerSourceUserId, setSharedResultsViewerSourceUserId] = useState<number | null>(null);
  const [sharedResultsViewerSourceUserName, setSharedResultsViewerSourceUserName] = useState('');
  const [sharedResultsViewerModels, setSharedResultsViewerModels] = useState<TexturedModel[]>([]);
  const [sharedResultsViewerHighlightedResultId, setSharedResultsViewerHighlightedResultId] = useState<string | null>(null);
  const [sharedResultsViewerSelectedResultIds, setSharedResultsViewerSelectedResultIds] = useState<string[]>([]);

  const tokenRef = useRef<string | null>(null);
  const sessionIdRef = useRef<number | null>(null);
  const texturePlanWriteVersionRef = useRef(0);
  const canvasInsertRequestRef = useRef(0);
  const designerCanvasRef = useRef<DesignerCanvasHandle | null>(null);

  const selectedTexturedModel = useMemo(
    () => texturedModels.find((model) => model.resultId === selectedTexturedResultId) ?? null,
    [selectedTexturedResultId, texturedModels],
  );

  const currentUserId = currentUser?.id ?? null;
  const currentUserIdString = currentUser ? String(currentUser.id) : '';
  const currentStorageUserKey = currentUser ? String(currentUser.id) : tabIdentitySeed;
  const ownSharedResultIds = useMemo(
    () => sessionMembers.find((member) => member.userId === currentUserId)?.sharedResultIds ?? [],
    [currentUserId, sessionMembers],
  );
  const visibleParticipants = useMemo<SessionMemberDirectoryEntry[]>(() => {
    const humanParticipants = sessionMembers.map((member) => ({
      ...member,
      participantType: member.participantType ?? 'human',
    }));
    if (uiStage < 2) {
      return humanParticipants;
    }
    const effectiveSettings = cloneMeetingSettings(meetingSettings);
    const enabledRoles = effectiveSettings.reviewPersonas.roles.filter((role) => role.enabled);
    const firstEngineeringId = enabledRoles.find((role) => role.type === 'engineering')?.id ?? '';
    const firstPassengerId = enabledRoles.find((role) => role.type === 'passenger')?.id ?? '';
    return [
      ...humanParticipants,
      ...enabledRoles.map((role, index) => ({
        userId:
          role.id === firstEngineeringId
            ? AGENT_MEMBER_IDS.engineering
            : role.id === firstPassengerId
              ? AGENT_MEMBER_IDS.passenger
              : -200 - index,
        name: role.displayName,
        role: 'observer' as const,
        joinedAt: '',
        online: true,
        publicShareCount: 0,
        canLiveSync: false,
        sharedResultIds: [],
        participantType: 'agent' as const,
        roleLabel:
          role.type === 'custom' ? '自定义评审' : role.type === 'engineering' ? '工程类评审' : '乘客类评审',
        agentShortcutKey: role.id === firstEngineeringId ? 'F' : role.id === firstPassengerId ? 'G' : undefined,
        agentDescription:
          role.type === 'custom'
            ? role.identitySummary || '按自定义身份和关注点提供角色化反馈。'
            : role.type === 'engineering'
            ? '评估可行性、工艺负担和制造风险。'
            : '给出乘客视角的快速反馈。',
      })),
    ];
  }, [meetingSettings, sessionMembers, uiStage]);
  const stage2ReviewCommentStates = useMemo(() => {
    const effectiveSettings = cloneMeetingSettings(meetingSettings);
    return {
      engineering: {
        label: effectiveSettings.reviewPersonas.engineering.displayName,
        shortcutKey: 'F',
        open: stage2CommentPanels.engineering.open,
        comment: getStage2QuickComment(selectedTexturedModel, 'engineering'),
        loading: stage2CommentPanels.engineering.loading,
        error: stage2CommentPanels.engineering.error,
      },
      passenger: {
        label: effectiveSettings.reviewPersonas.passenger.displayName,
        shortcutKey: 'G',
        open: stage2CommentPanels.passenger.open,
        comment: getStage2QuickComment(selectedTexturedModel, 'passenger'),
        loading: stage2CommentPanels.passenger.loading,
        error: stage2CommentPanels.passenger.error,
      },
    };
  }, [meetingSettings, selectedTexturedModel, stage2CommentPanels]);

  const reviewSourceModels = uiStage >= 3 ? meetingSharedReviewModels : texturedModels;
  const reviewSchemes = useMemo<ReviewScheme[]>(
    () =>
      buildReviewSchemes(reviewSourceModels, baseModel, meetingSettings).map((scheme) => ({
        ...scheme,
        starredBy: starredSchemes[scheme.resultId] ?? [],
      })),
    [baseModel, meetingSettings, reviewSourceModels, starredSchemes],
  );

  const selectedTexturePreviewMode: TexturePreviewMode = useMemo(() => {
    if (!selectedTexturedModel) {
      return 'meshy';
    }
    const requestedMode = previewModeByResultId[selectedTexturedModel.resultId];
    if (requestedMode === 'edited' && selectedTexturedModel.editedVariant?.modelUrl) {
      return 'edited';
    }
    return 'meshy';
  }, [previewModeByResultId, selectedTexturedModel]);

  const selectedTexturedPreviewUrl = useMemo(() => {
    if (!selectedTexturedModel) {
      return null;
    }
    if (selectedTexturePreviewMode === 'edited') {
      return selectedTexturedModel.editedVariant?.modelUrl ?? selectedTexturedModel.texturedModelUrl;
    }
    return selectedTexturedModel.texturedModelUrl;
  }, [selectedTexturedModel, selectedTexturePreviewMode]);

  const selectedPatternTextureUrl = useMemo(() => {
    if (!selectedTexturedModel) {
      return null;
    }
    if (selectedTexturePreviewMode === 'edited' && selectedTexturedModel.editedVariant?.baseColorUrl) {
      return selectedTexturedModel.editedVariant.baseColorUrl;
    }
    return selectedTexturedModel.textureMaps?.baseColor ?? selectedTexturedModel.editedVariant?.baseColorUrl ?? null;
  }, [selectedTexturedModel, selectedTexturePreviewMode]);

  const canGeneratePattern = Boolean(token && sessionId && selectedTexturedModel && selectedPatternTextureUrl);

  const textureCanvasSize = useMemo(() => {
    const width = baseModel?.mappingMeta?.uvSpec?.width;
    const height = baseModel?.mappingMeta?.uvSpec?.height;
    if (
      typeof width === 'number' &&
      Number.isFinite(width) &&
      width > 0 &&
      typeof height === 'number' &&
      Number.isFinite(height) &&
      height > 0
    ) {
      return { width, height };
    }
    return null;
  }, [baseModel?.mappingMeta?.uvSpec?.height, baseModel?.mappingMeta?.uvSpec?.width]);

  useEffect(() => {
    tokenRef.current = token;
  }, [token]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setLinkedUvFocus(null);
  }, [baseModel?.baseModelId]);

  useEffect(() => {
    const persistedTextureWorkspace = readPersistedTextureWorkspaceState(
      sessionId,
      baseModel?.baseModelId ?? null,
      currentStorageUserKey,
    );
    setActiveTextureWorkspaceId(
      persistedTextureWorkspace?.activeTextureWorkspaceId ?? getTextureWorkspaceId(baseModel?.baseModelId ?? null, null),
    );
    setWorkspaceHasContent({});
    setCanvasTextureLayer(
      persistedTextureWorkspace?.canvasTextureLayer
        ? {
            requestId: ++canvasInsertRequestRef.current,
            ...persistedTextureWorkspace.canvasTextureLayer,
          }
        : null,
    );
  }, [baseModel?.baseModelId, currentStorageUserKey, sessionId]);

  useEffect(() => {
    setStarredSchemes(readPersistedReviewStars(sessionId, currentStorageUserKey));
  }, [currentStorageUserKey, sessionId]);

  useEffect(() => {
    if (!selectedTexturedModel) {
      return;
    }
    setActiveTextureWorkspaceId(getTextureWorkspaceId(baseModel?.baseModelId ?? null, selectedTexturedModel));
  }, [baseModel?.baseModelId, selectedTexturedModel]);

  useEffect(() => {
    setPatternPreviewItem(null);
  }, [selectedTexturedResultId, selectedTexturePreviewMode]);

  useEffect(() => {
    setStage2CommentPanels(DEFAULT_STAGE2_COMMENT_PANEL_STATE);
  }, [selectedTexturedResultId]);

  useEffect(() => {
    setCanvasHasSelection(false);
  }, [activeTextureWorkspaceId, uiStage]);

  useEffect(() => {
    if (uiStage !== 2) {
      setPatternPopoverOpen(false);
      setPatternPreviewItem(null);
      setStage2CommentPanels(DEFAULT_STAGE2_COMMENT_PANEL_STATE);
    }
  }, [uiStage]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.sessionStorage.setItem(DISPLAY_NAME_STORAGE_KEY, displayName);
  }, [displayName]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.sessionStorage.setItem(INVITE_CODE_STORAGE_KEY, inviteCode);
  }, [inviteCode]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.sessionStorage.setItem(ROLE_STORAGE_KEY, selectedRole);
  }, [selectedRole]);

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionId) {
      return;
    }
    const payload: PersistedTextureWorkspaceState = {
      selectedTexturedResultId,
      activeTextureWorkspaceId,
      previewModeByResultId,
      canvasTextureLayer: canvasTextureLayer
        ? {
            workspaceId: canvasTextureLayer.workspaceId,
            imageUrl: canvasTextureLayer.imageUrl,
            label: canvasTextureLayer.label,
          }
        : null,
    };
    window.localStorage.setItem(
      getTextureWorkspaceStorageKey(sessionId, baseModel?.baseModelId ?? null, currentStorageUserKey),
      JSON.stringify(payload),
    );
  }, [
    activeTextureWorkspaceId,
    baseModel?.baseModelId,
    canvasTextureLayer,
    currentStorageUserKey,
    previewModeByResultId,
    selectedTexturedResultId,
    sessionId,
  ]);

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionId) {
      return;
    }
    window.localStorage.setItem(
      getReviewStarStorageKey(sessionId, currentStorageUserKey),
      JSON.stringify(starredSchemes),
    );
  }, [currentStorageUserKey, sessionId, starredSchemes]);

  const syncTexturePlan = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      setTexturePlanLoading(true);
      const nextTexturePlan = await fetchTexturePlan(tokenRef.current, sessionIdRef.current);
      setTexturePlan(nextTexturePlan);
    } catch {
      // ignore sync failures in polling path
    } finally {
      setTexturePlanLoading(false);
    }
  }, []);

  const syncTextureModels = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      const nextTextureModels = await fetchTextureModels(tokenRef.current, { sessionId: sessionIdRef.current });
      setTextureModelsStatus(nextTextureModels.status);
      setTexturedModels(nextTextureModels.models);
      setSelectedTexturedResultId((current) => {
        if (current && nextTextureModels.models.some((model) => model.resultId === current)) {
          return current;
        }
        const firstCompleted = nextTextureModels.models.find((model) => model.status === 'completed' && model.texturedModelUrl);
        return firstCompleted?.resultId ?? null;
      });
      setPreviewModeByResultId((current) => {
        const next: Record<string, TexturePreviewMode> = {};
        for (const model of nextTextureModels.models) {
          const existingMode = current[model.resultId];
          if (existingMode === 'edited' && model.editedVariant?.modelUrl) {
            next[model.resultId] = 'edited';
            continue;
          }
          if (!existingMode && model.editedVariant?.modelUrl) {
            next[model.resultId] = 'edited';
            continue;
          }
          next[model.resultId] = 'meshy';
        }
        return next;
      });
    } catch {
      // ignore texture model sync failures
    }
  }, []);

  const syncSessionMembers = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      const nextMembers = await fetchSessionMembers(tokenRef.current, sessionIdRef.current);
      setSessionMembers(nextMembers.members);
    } catch {
      // ignore member directory sync failures
    }
  }, []);

  const syncMeetingSharedReviewModels = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      const nextSharedModels = await fetchStage3SharedTextureModels(tokenRef.current, {
        sessionId: sessionIdRef.current,
      });
      setMeetingSharedReviewModels(nextSharedModels.models);
    } catch {
      // ignore shared review sync failures
    }
  }, []);

  const handleStageChangedEvent = useCallback((payload: { session_id: number; stage: string }) => {
    const nextStage = payload.stage as SessionStage;
    setBackendStage(nextStage);
    setUiStage(mapBackendStageToUiStage(nextStage));
  }, []);

  const handleBriefPublishedEvent = useCallback((payload: { brief_json: unknown }) => {
    if (payload.brief_json && typeof payload.brief_json === 'object') {
      setBrief(payload.brief_json as DesignBrief);
    }
  }, []);

  const handleModelTaskStatusEvent = useCallback(
    (payload: { status: string; progress: number; pipeline_stage?: string | null; progress_message?: string | null }) => {
      setModelTaskStatus(payload.status);
      setModelTaskProgress(payload.progress);
      setModelPipelineStage(payload.pipeline_stage ?? null);
      setModelProgressMessage(payload.progress_message ?? null);
      if (payload.status === 'ready' || payload.status === 'failed') {
        setModelPreparing(false);
      }
    },
    [],
  );

  const handleModelReadyEvent = useCallback((payload: { model?: unknown }) => {
    if (!payload.model || typeof payload.model !== 'object') {
      return;
    }
    setModelTaskStatus('ready');
    setModelTaskProgress(100);
    setModelPipelineStage('ready');
    setModelProgressMessage('UV template ready');
    setModelPreparing(false);
    setBackendStage('MODEL_PREPARING');
    setUiStage(1);

    setBaseModel(toBaseModelFromSocket(payload.model as SocketModelPayload));
    setBaseModelLocked(false);
  }, []);

  const handleModelLockedEvent = useCallback((payload: { model?: unknown; model_locked_at?: string | null }) => {
    if (payload.model && typeof payload.model === 'object') {
      setBaseModel(toBaseModelFromSocket(payload.model as SocketModelPayload, payload.model_locked_at));
    }
    setBaseModelLocked(true);
    setBackendStage('MODEL_PREPARING');
    setUiStage(1);
  }, []);

  const handleTexturePlanUpdatedEvent = useCallback(() => {
    void syncTexturePlan();
  }, [syncTexturePlan]);

  const handleTextureModelsUpdatedEvent = useCallback(() => {
    void syncTextureModels();
    if (uiStage >= 3) {
      void syncMeetingSharedReviewModels();
    }
  }, [syncMeetingSharedReviewModels, syncTextureModels, uiStage]);

  const handleSessionMembersUpdatedEvent = useCallback(() => {
    void syncSessionMembers();
  }, [syncSessionMembers]);

  const rtc = useMeetingRtc({
    enabled: screen === 'meeting' && Boolean(token) && Boolean(sessionId) && Boolean(currentUser),
    token,
    sessionId,
    user: currentUser,
    role: meetingRole,
    initialStream: preJoinSettings?.localStream ?? null,
    initialAudioEnabled: preJoinSettings?.audioEnabled ?? false,
    initialVideoEnabled: preJoinSettings?.videoEnabled ?? false,
    selectedAudioDeviceId: preJoinSettings?.selectedAudioDeviceId,
    selectedVideoDeviceId: preJoinSettings?.selectedVideoDeviceId,
    onStageChanged: handleStageChangedEvent,
    onBriefPublished: handleBriefPublishedEvent,
    onModelTaskStatus: handleModelTaskStatusEvent,
    onModelReady: handleModelReadyEvent,
    onModelLocked: handleModelLockedEvent,
    onTexturePlanUpdated: handleTexturePlanUpdatedEvent,
    onTextureModelsUpdated: handleTextureModelsUpdatedEvent,
    onSessionMembersUpdated: handleSessionMembersUpdatedEvent,
  });

  useEffect(() => {
    if (screen !== 'meeting' || !token || !sessionId) {
      return;
    }
    void syncSessionMembers();
  }, [rtc.peers.length, screen, sessionId, syncSessionMembers, token]);

  useEffect(() => {
    if (screen !== 'meeting' || !token || !sessionId) {
      return;
    }
    if (uiStage >= 3) {
      void syncMeetingSharedReviewModels();
      return;
    }
    setMeetingSharedReviewModels([]);
  }, [screen, sessionId, syncMeetingSharedReviewModels, token, uiStage]);

  const isHost = meetingRole === 'host';
  const canModifyWorkspace = meetingRole !== 'observer';

  const hydrateSessionStageState = useCallback(
    (session: {
      design_goal_text?: string | null;
      product_category?: ProductCategory | null;
      product_profile?: ProductProfile | null;
      brief_json?: DesignBrief | null;
    }) => {
      setDesignGoal(
        typeof session.design_goal_text === 'string' && session.design_goal_text.trim().length > 0
          ? session.design_goal_text
          : DEFAULT_DESIGN_GOAL,
      );
      setProductCategory(session.product_category ?? DEFAULT_PRODUCT_CATEGORY);
      setProductProfile(normalizeProductProfile(session.product_profile));
      setBrief(session.brief_json ?? null);
    },
      [],
    );

  const hydrateSessionSettingsState = useCallback(
    (session: {
      session_settings?: MeetingSettings | null;
      settings_permissions?: MeetingSettingsPermissions | null;
      settings_sections?: MeetingSettingsSection[];
    }) => {
      setMeetingSettings(cloneMeetingSettings(session.session_settings));
      setMeetingSettingsPermissions(session.settings_permissions ?? null);
      setMeetingSettingsSections(session.settings_sections ?? []);
    },
    [],
  );

  const syncMeetingSettings = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return null;
    }
    const next = await fetchSessionSettings(tokenRef.current, sessionIdRef.current);
    setMeetingSettings(cloneMeetingSettings(next.sessionSettings));
    setMeetingSettingsPermissions(next.settingsPermissions);
    setMeetingSettingsSections(next.sections);
    return next;
  }, []);

  const syncSessionBaseModel = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      const baseModelState = await fetchSessionBaseModel(tokenRef.current, sessionIdRef.current);
      if (baseModelState.baseModel) {
        setBaseModel(baseModelState.baseModel);
        setBaseModelLocked(Boolean(baseModelState.modelLockedAt));
        return;
      }

      // A previous bad lock can leave model_locked_at set while the model payload is missing.
      // Keep any newly prepared local upload visible so the host can lock it and repair the session.
      setBaseModel((current) => current);
      setBaseModelLocked(false);
    } catch {
      // ignore sync failures in polling path
    }
  }, []);

  const handleEnterPreJoin = () => {
    if (displayName.trim().length === 0) {
      setJoinError('请输入姓名。');
      return;
    }
    if (inviteCode.trim().length < 4) {
      setJoinError('邀请码无效。');
      return;
    }
    setJoinError(null);
    setScreen('prejoin');
  };

  const handleJoinMeeting = useCallback(
    async (settings: PreJoinSettings) => {
      setJoining(true);
      setJoinError(null);

      try {
        const auth = await ensureUserToken(displayName, DEFAULT_PASSWORD, tabIdentitySeed);
        const joined = await joinSessionByInvite(auth.token, inviteCode, settings.role);
        const shouldClearSessionCache =
          joined.session.stage === 'LOBBY' &&
          !joined.session.base_model_id &&
          !joined.session.brief_json &&
          !(joined.session.design_goal_text && joined.session.design_goal_text.trim().length > 0);
          if (shouldClearSessionCache) {
            clearSessionWorkspaceCache(joined.session.id, auth.user.id);
          }
          hydrateSessionStageState(joined.session);
          hydrateSessionSettingsState(joined.session);

        setToken(auth.token);
        setCurrentUser(auth.user);
        setSessionId(joined.session.id);
        setSessionName(joined.session.name);
        setBackendStage(joined.session.stage);
        setUiStage(mapBackendStageToUiStage(joined.session.stage));
        setStageAdvancing(false);
        setStageReverting(false);
        setMeetingRole(joined.role);
        setSelectedRole(joined.role);
        setPreJoinSettings(settings);
        setScreen('meeting');

        const baseModelState = await fetchSessionBaseModel(auth.token, joined.session.id);
        const persistedTextureWorkspace = readPersistedTextureWorkspaceState(
          joined.session.id,
          baseModelState.baseModel?.baseModelId ?? null,
          auth.user.id,
        );
        setBaseModel(baseModelState.baseModel ?? null);
        setBaseModelLocked(Boolean(baseModelState.modelLockedAt));

        try {
          const nextTexturePlan = await fetchTexturePlan(auth.token, joined.session.id);
          setTexturePlan(nextTexturePlan);
        } catch {
          setTexturePlan(null);
        }
        try {
          const nextTextureModels = await fetchTextureModels(auth.token, { sessionId: joined.session.id });
          const nextPreviewModes = Object.fromEntries(
            nextTextureModels.models.map((model) => {
              const persistedMode = persistedTextureWorkspace?.previewModeByResultId[model.resultId];
              if (persistedMode === 'edited' && model.editedVariant?.modelUrl) {
                return [model.resultId, 'edited'];
              }
              if (persistedMode === 'meshy') {
                return [model.resultId, 'meshy'];
              }
              return [model.resultId, model.editedVariant?.modelUrl ? 'edited' : 'meshy'];
            }),
          ) as Record<string, TexturePreviewMode>;
          const firstCompleted = nextTextureModels.models.find(
            (model) => model.status === 'completed' && model.texturedModelUrl,
          );
          const restoredSelectedTexturedResultId =
            persistedTextureWorkspace?.selectedTexturedResultId &&
            nextTextureModels.models.some((model) => model.resultId === persistedTextureWorkspace.selectedTexturedResultId)
              ? persistedTextureWorkspace.selectedTexturedResultId
              : firstCompleted?.resultId ?? null;
          const restoredSelectedModel =
            nextTextureModels.models.find((model) => model.resultId === restoredSelectedTexturedResultId) ?? null;
          const defaultWorkspaceId = getTextureWorkspaceId(
            baseModelState.baseModel?.baseModelId ?? null,
            restoredSelectedModel,
          );
          const restoredWorkspaceId =
            persistedTextureWorkspace?.activeTextureWorkspaceId?.startsWith(
              `workspace:${baseModelState.baseModel?.baseModelId ?? 'no-model'}:`,
            )
              ? persistedTextureWorkspace.activeTextureWorkspaceId
              : defaultWorkspaceId;

          setTextureModelsStatus(nextTextureModels.status);
          setTexturedModels(nextTextureModels.models);
          setSelectedTexturedResultId(restoredSelectedTexturedResultId);
          setPreviewModeByResultId(nextPreviewModes);
          setActiveTextureWorkspaceId(restoredWorkspaceId);
          setCanvasTextureLayer(
            persistedTextureWorkspace?.canvasTextureLayer &&
              persistedTextureWorkspace.canvasTextureLayer.workspaceId === restoredWorkspaceId
              ? {
                  requestId: ++canvasInsertRequestRef.current,
                  ...persistedTextureWorkspace.canvasTextureLayer,
                }
              : null,
          );
        } catch {
          setTextureModelsStatus('idle');
          setTexturedModels([]);
          setSelectedTexturedResultId(null);
          setPreviewModeByResultId({});
          setActiveTextureWorkspaceId(getTextureWorkspaceId(baseModelState.baseModel?.baseModelId ?? null, null));
          setCanvasTextureLayer(null);
        }
        if (mapBackendStageToUiStage(joined.session.stage) >= 3) {
          try {
            const nextSharedModels = await fetchStage3SharedTextureModels(auth.token, { sessionId: joined.session.id });
            setMeetingSharedReviewModels(nextSharedModels.models);
          } catch {
            setMeetingSharedReviewModels([]);
          }
        } else {
          setMeetingSharedReviewModels([]);
        }
        try {
          const nextMembers = await fetchSessionMembers(auth.token, joined.session.id);
          setSessionMembers(nextMembers.members);
        } catch {
          setSessionMembers([]);
        }
      } catch (error) {
        setJoinError(parseApiError(error, '进入协作空间失败。'));
      } finally {
        setJoining(false);
      }
    },
      [displayName, hydrateSessionSettingsState, hydrateSessionStageState, inviteCode, tabIdentitySeed],
    );

  const handleLeaveMeeting = useCallback(() => {
    rtc.leaveMeeting();
    setScreen('entry');
    setToken(null);
    setCurrentUser(null);
    setSessionId(null);
    setSessionName('');
    setMeetingRole('designer');
    setSelectedRole('designer');
    setPreJoinSettings(null);
      setJoinError(null);
      setUiStage(1);
      setBackendStage('LOBBY');
      setMeetingSettings(null);
      setMeetingSettingsPermissions(null);
      setMeetingSettingsSections([]);
      setMeetingSettingsOpen(false);
      setMeetingSettingsLoading(false);
      setMeetingSettingsSaving(false);
      setActiveMeetingSettingsSection('review_roles');
      setStageAdvancing(false);
      setStageReverting(false);
    setDesignGoal(DEFAULT_DESIGN_GOAL);
    setProductCategory(DEFAULT_PRODUCT_CATEGORY);
    setModelSource('upload');
    setProductProfile(cloneDefaultProductProfile());
    setBrief(null);
    setBaseModel(null);
    setBaseModelLocked(false);
    setUploadedModelFile(null);
    setModelTaskStatus(null);
    setModelTaskProgress(0);
    setModelPipelineStage(null);
    setModelProgressMessage(null);
    setModelPreparing(false);
    setTexturePlan(null);
    setTexturePlanLoading(false);
    setTexturePlanGenerating(false);
    setTexturePlanSaving(false);
    setTextureImageAnalyzing(false);
    setTextureModelsStatus('idle');
    setTexturedModels([]);
    setMeetingSharedReviewModels([]);
    setSelectedTexturedResultId(null);
    setPreviewModeByResultId({});
    setApplyTexturePending(false);
    setDeletingTexturedResultId(null);
    setRefreshReviewPendingResultId(null);
    setStage2CommentPanels(DEFAULT_STAGE2_COMMENT_PANEL_STATE);
    setWorkspaceHasContent({});
    setCanvasInsertAsset(null);
    setPatternPopoverOpen(false);
    setPatternPromptText('');
    setPatternGenerating(false);
    setPatternPreviewItem(null);
    setCanvasTextureLayer(null);
    setStarredSchemes({});
    setSessionMembers([]);
    setSharingResultsPending(false);
    setSharedResultsViewerOpen(false);
    setSharedResultsViewerLoading(false);
    setSharedResultsViewerImporting(false);
    setSharedResultsViewerSourceUserId(null);
    setSharedResultsViewerSourceUserName('');
    setSharedResultsViewerModels([]);
    setSharedResultsViewerHighlightedResultId(null);
    setSharedResultsViewerSelectedResultIds([]);
    setLastAutoSavedAt('');
    setLinkedUvFocus(null);
  }, [rtc]);

  const handleAdvanceStage = useCallback(async () => {
    if (!token || !sessionId || stageAdvancing) {
      return;
    }

    try {
        setStageAdvancing(true);
        setJoinError(null);
        const next = await advanceSessionStage(token, sessionId);
        hydrateSessionSettingsState(next);
        setBackendStage(next.stage);
        setUiStage(mapBackendStageToUiStage(next.stage));
      } catch (error) {
        setJoinError(parseApiError(error, '推进阶段失败。'));
      } finally {
        setStageAdvancing(false);
      }
    }, [hydrateSessionSettingsState, sessionId, stageAdvancing, token]);

  const handleRevertStage = useCallback(async () => {
    if (!token || !sessionId || stageReverting) {
      return;
    }

    try {
        setStageReverting(true);
        setJoinError(null);
        const next = await revertSessionStage(token, sessionId);
        hydrateSessionStageState(next);
        hydrateSessionSettingsState(next);
        setBackendStage(next.stage);
        setUiStage(mapBackendStageToUiStage(next.stage));
        await Promise.all([syncSessionBaseModel(), syncTexturePlan(), syncTextureModels(), syncSessionMembers()]);
    } catch (error) {
      setJoinError(parseApiError(error, '返回上一阶段失败。'));
    } finally {
      setStageReverting(false);
    }
  }, [
      hydrateSessionSettingsState,
      hydrateSessionStageState,
      sessionId,
    stageReverting,
    syncSessionBaseModel,
    syncSessionMembers,
    syncTextureModels,
    syncTexturePlan,
    token,
  ]);

  const handleStarScheme = useCallback(
    (resultId: string) => {
      if (!currentUserIdString) {
        return;
      }
      setStarredSchemes((current) => {
        const currentUsers = current[resultId] ?? [];
        const nextUsers = currentUsers.includes(currentUserIdString)
          ? currentUsers.filter((userId) => userId !== currentUserIdString)
          : [...currentUsers, currentUserIdString];
        return {
          ...current,
          [resultId]: nextUsers,
        };
      });
    },
    [currentUserIdString],
  );

  useEffect(() => {
    if (screen !== 'meeting' || !token || !sessionId) {
      return;
    }

    const timer = window.setInterval(() => {
      void (async () => {
          try {
            const latest = await fetchSessionDetail(token, sessionId);
            if (!meetingSettingsOpen) {
              hydrateSessionSettingsState(latest);
            }
            setBackendStage(latest.stage);
            setSessionName(latest.name);
            setUiStage(mapBackendStageToUiStage(latest.stage));
            await syncSessionBaseModel();
          } catch {
          // polling failure should not break current session UI
        }
      })();
    }, 6000);

    return () => {
      window.clearInterval(timer);
    };
    }, [hydrateSessionSettingsState, meetingSettingsOpen, screen, sessionId, syncSessionBaseModel, syncTexturePlan, token]);

  const handleParseBrief = useCallback(async () => {
    if (!token || !sessionId || !isHost) {
      return;
    }

    try {
      setJoinError(null);
      const parsed = await parseBrief(token, {
        sessionId,
        designGoal,
        productCategory,
      });
      setBrief(parsed.brief);
      setBackendStage(parsed.stage);
      setUiStage(mapBackendStageToUiStage(parsed.stage));
      void syncTexturePlan();
    } catch (error) {
      setJoinError(parseApiError(error, '解析需求失败。'));
    }
  }, [designGoal, isHost, productCategory, sessionId, syncTexturePlan, token]);

  const prepareBaseModelFromFile = useCallback(async (file: File) => {
    if (!token || !sessionId || !isHost || modelPreparing) {
      return;
    }

    try {
      setJoinError(null);
      setModelPreparing(true);
      setModelTaskStatus('queued');
      setModelTaskProgress(0);
      setModelPipelineStage('queued');
      setModelProgressMessage('已收到上传文件');
      setBaseModelLocked(false);

      if (modelSource !== 'upload') {
        throw new Error('当前版本仅支持上传 3D 模型。');
      }
      setUploadedModelFile(file);
      setBaseModel(null);
      setModelTaskStatus('uploading');
      setModelProgressMessage(`正在上传 ${file.name}`);

      const uploaded = await uploadModel(token, sessionId, productCategory, file);
      setBackendStage('MODEL_PREPARING');
      setUiStage(1);
      setModelTaskStatus(uploaded.status);
      setModelTaskProgress(uploaded.progress);
      setModelPipelineStage(uploaded.pipelineStage);
      setModelProgressMessage('已进入模型处理队列');

      let readyModel: BaseModelMeta | null = null;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const task = await fetchModelTask(token, uploaded.taskId);
        setModelTaskStatus(task.status);
        setModelTaskProgress(task.progress);
        setModelPipelineStage(task.pipelineStage);
        setModelProgressMessage(task.progressMessage);

        if (task.status === 'failed') {
          throw new Error(task.errorMessage ?? '模型处理失败。');
        }
        if (task.status === 'ready' && task.resultModel) {
          readyModel = task.resultModel;
          break;
        }
        await delay(1200);
      }

      if (!readyModel) {
        throw new Error('模型处理超时。');
      }

      setBaseModel(readyModel);
      setBaseModelLocked(false);
    } catch (error) {
      setJoinError(parseApiError(error, '准备基础模型失败。'));
    } finally {
      setModelPreparing(false);
    }
  }, [isHost, modelPreparing, modelSource, productCategory, sessionId, token]);

  const handleUploadFileSelected = useCallback(
    (file: File | null) => {
      setUploadedModelFile(file);
      if (!file) {
        return;
      }
      void prepareBaseModelFromFile(file);
    },
    [prepareBaseModelFromFile],
  );

  const handleLockBaseModel = useCallback(async () => {
    if (!token || !sessionId || !baseModel || !isHost) {
      return;
    }

    try {
      setJoinError(null);
      const result = await selectBaseModel(token, sessionId, baseModel.baseModelId);
      setBaseModel({
        ...baseModel,
        lockedAt: result.modelLockedAt ?? new Date().toISOString(),
      });
      setBaseModelLocked(true);
      setBackendStage('MODEL_PREPARING');
      setUiStage(1);
    } catch (error) {
      setJoinError(parseApiError(error, '锁定基础模型失败。'));
    }
  }, [baseModel, isHost, sessionId, token]);

  const handleAutoSave = useCallback(
    (resultId: string, snapshot: string) => {
      if (typeof window === 'undefined' || !sessionId) {
        return;
      }
      window.localStorage.setItem(
        getCanvasSnapshotStorageKey(sessionId, baseModel?.baseModelId ?? null, currentStorageUserKey, resultId),
        snapshot,
      );
      setLastAutoSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    },
    [baseModel?.baseModelId, currentStorageUserKey, sessionId],
  );

  const handleGenerateModelTextures = useCallback(
    async (payload: {
      sourceText: string;
      documentFile: File | null;
      referenceImageFile: File | null;
      selectedImageKeywords: string[];
    }): Promise<boolean> => {
      if (!token || !sessionId) {
        return false;
      }

      const requestVersion = ++texturePlanWriteVersionRef.current;
      try {
        setTexturePlanGenerating(true);
        setJoinError(null);
        setTextureModelsStatus('queued');
        const accepted = await startGenerateModelTextures(token, {
          sessionId,
          sourceText: payload.sourceText,
          documentFile: payload.documentFile,
          referenceImageFile: payload.referenceImageFile,
          selectedImageKeywords: payload.selectedImageKeywords,
        });
        if (accepted.status === 'accepted') {
          void syncTextureModels();
        }
        return accepted.status === 'accepted';
      } catch (error) {
        setJoinError(parseApiError(error, '生成重新纹理方案失败。'));
        if (requestVersion === texturePlanWriteVersionRef.current) {
          void syncTexturePlan();
        }
        setTextureModelsStatus('failed');
        return false;
      } finally {
        setTexturePlanGenerating(false);
      }
    },
    [baseModel?.baseModelId, sessionId, syncTexturePlan, token],
  );

  const handleUploadCustomTexturedModel = useCallback(
    async (payload: {
      title: string;
      modelFile: File;
      baseColorFile: File;
    }): Promise<boolean> => {
      if (!token || !sessionId) {
        return false;
      }

      try {
        setJoinError(null);
        const nextState = await uploadCustomTexturedModel(token, {
          sessionId,
          title: payload.title,
          modelFile: payload.modelFile,
          baseColorFile: payload.baseColorFile,
        });
        setTextureModelsStatus(nextState.status);
        setTexturedModels(nextState.models);
        const uploadedModel = nextState.models[nextState.models.length - 1] ?? null;
        if (uploadedModel?.resultId) {
          setSelectedTexturedResultId(uploadedModel.resultId);
          setPreviewModeByResultId((current) => ({
            ...current,
            [uploadedModel.resultId]: uploadedModel.editedVariant?.modelUrl ? 'edited' : 'meshy',
          }));
        }
        return true;
      } catch (error) {
        setJoinError(parseApiError(error, '上传自定义纹理方案失败。'));
        return false;
      }
    },
    [sessionId, token],
  );

  const handleAnalyzeTextureImage = useCallback(
    async (referenceImageFile: File) => {
      if (!token || !sessionId) {
        return;
      }

      const requestVersion = ++texturePlanWriteVersionRef.current;
      try {
        setTextureImageAnalyzing(true);
        setJoinError(null);
        const nextTexturePlan = await analyzeTexturePlanImage(token, {
          sessionId,
          referenceImageFile,
        });
        if (requestVersion === texturePlanWriteVersionRef.current) {
          setTexturePlan(nextTexturePlan);
        }
      } catch (error) {
        setJoinError(parseApiError(error, '分析参考图失败。'));
      } finally {
        setTextureImageAnalyzing(false);
      }
    },
    [sessionId, token],
  );

  const handleUpdateSelectedImageKeywords = useCallback(
    async (selectedImageKeywords: string[]) => {
      if (!token || !sessionId) {
        return;
      }

      const requestVersion = ++texturePlanWriteVersionRef.current;
      setTexturePlan((current) =>
        current
          ? {
              ...current,
              selectedImageKeywords,
            }
          : current,
      );

      try {
        setTexturePlanSaving(true);
        const nextTexturePlan = await patchTexturePlan(token, {
          sessionId,
          selectedImageKeywords,
        });
        if (requestVersion === texturePlanWriteVersionRef.current) {
          setTexturePlan(nextTexturePlan);
        }
      } catch (error) {
        setJoinError(parseApiError(error, '保存图像关键词失败。'));
        void syncTexturePlan();
      } finally {
        setTexturePlanSaving(false);
      }
    },
    [sessionId, syncTexturePlan, token],
  );

  const handleRemoveTextureDocument = useCallback(async () => {
    if (!token || !sessionId) {
      return;
    }

    const requestVersion = ++texturePlanWriteVersionRef.current;
    setTexturePlan((current) =>
      current
        ? {
            ...current,
            documentName: null,
            documentExcerpt: '',
          }
        : current,
    );

    try {
      setTexturePlanSaving(true);
      const nextTexturePlan = await patchTexturePlan(token, {
        sessionId,
        clearDocument: true,
      });
      if (requestVersion === texturePlanWriteVersionRef.current) {
        setTexturePlan(nextTexturePlan);
      }
    } catch (error) {
      setJoinError(parseApiError(error, '移除文档失败。'));
      void syncTexturePlan();
    } finally {
      setTexturePlanSaving(false);
    }
  }, [sessionId, syncTexturePlan, token]);

  const handleRemoveTextureImage = useCallback(async () => {
    if (!token || !sessionId) {
      return;
    }

    const requestVersion = ++texturePlanWriteVersionRef.current;
    setTexturePlan((current) =>
      current
        ? {
            ...current,
            imageName: null,
            imageContentKeywords: [],
            imageStyleKeywords: [],
            selectedImageKeywords: [],
          }
        : current,
    );

    try {
      setTexturePlanSaving(true);
      const nextTexturePlan = await patchTexturePlan(token, {
        sessionId,
        clearImage: true,
      });
      if (requestVersion === texturePlanWriteVersionRef.current) {
        setTexturePlan(nextTexturePlan);
      }
    } catch (error) {
      setJoinError(parseApiError(error, '移除参考图失败。'));
      void syncTexturePlan();
    } finally {
      setTexturePlanSaving(false);
    }
  }, [sessionId, syncTexturePlan, token]);

  const handleDeleteTexturedModel = useCallback(
    async (resultId: string): Promise<boolean> => {
      if (!token || !sessionId || !resultId) {
        return false;
      }

      const targetModel = texturedModels.find((item) => item.resultId === resultId);
      if (!targetModel) {
        return false;
      }

      const deletedWorkspaceId = getTextureWorkspaceId(baseModel?.baseModelId ?? null, targetModel);

      try {
        setDeletingTexturedResultId(resultId);
        setJoinError(null);
        const nextState = await deleteTextureModel(token, {
          sessionId,
          resultId,
        });
        const fallbackSelectedResultId =
          selectedTexturedResultId && nextState.models.some((model) => model.resultId === selectedTexturedResultId)
            ? selectedTexturedResultId
            : nextState.models.find((model) => model.status === 'completed' && model.texturedModelUrl)?.resultId ?? null;
        const fallbackSelectedModel =
          nextState.models.find((model) => model.resultId === fallbackSelectedResultId) ?? null;

        if (typeof window !== 'undefined') {
          window.localStorage.removeItem(
            getCanvasSnapshotStorageKey(
              sessionId,
              baseModel?.baseModelId ?? null,
              currentStorageUserKey,
              deletedWorkspaceId,
            ),
          );
        }

        setTextureModelsStatus(nextState.status);
        setTexturedModels(nextState.models);
        setSelectedTexturedResultId(fallbackSelectedResultId);
        setPreviewModeByResultId((current) =>
          Object.fromEntries(
            nextState.models.map((model) => {
              const existingMode = current[model.resultId];
              if (existingMode === 'edited' && model.editedVariant?.modelUrl) {
                return [model.resultId, 'edited'];
              }
              if (!existingMode && model.editedVariant?.modelUrl) {
                return [model.resultId, 'edited'];
              }
              return [model.resultId, 'meshy'];
            }),
          ) as Record<string, TexturePreviewMode>,
        );
        setWorkspaceHasContent((current) => {
          if (!(deletedWorkspaceId in current)) {
            return current;
          }
          const next = { ...current };
          delete next[deletedWorkspaceId];
          return next;
        });
        setCanvasTextureLayer((current) => (current?.workspaceId === deletedWorkspaceId ? null : current));
        setStarredSchemes((current) => {
          if (!(resultId in current)) {
            return current;
          }
          const next = { ...current };
          delete next[resultId];
          return next;
        });
        setActiveTextureWorkspaceId((current) =>
          current === deletedWorkspaceId
            ? getTextureWorkspaceId(baseModel?.baseModelId ?? null, fallbackSelectedModel)
            : current,
        );
        void syncSessionMembers();
        if (uiStage >= 3) {
          void syncMeetingSharedReviewModels();
        }
        return true;
      } catch (error) {
        setJoinError(parseApiError(error, '删除纹理方案失败。'));
        return false;
      } finally {
        setDeletingTexturedResultId(null);
      }
    },
    [
      baseModel?.baseModelId,
      currentStorageUserKey,
      selectedTexturedResultId,
      sessionId,
      syncMeetingSharedReviewModels,
      syncSessionMembers,
      texturedModels,
      token,
      uiStage,
    ],
  );

  const handleSelectTexturedModel = useCallback((resultId: string) => {
    if (!resultId) {
      setSelectedTexturedResultId(null);
      return;
    }
    const model = texturedModels.find((m) => m.resultId === resultId);
    if (model?.texturedModelUrl) {
      setSelectedTexturedResultId(model.resultId);
      setPreviewModeByResultId((current) => ({
        ...current,
        [model.resultId]: model.editedVariant?.modelUrl ? current[model.resultId] ?? 'edited' : 'meshy',
      }));
    }
  }, [texturedModels]);

  const handleAddTextureToCanvas = useCallback((resultId: string) => {
    const model = texturedModels.find((item) => item.resultId === resultId);
    if (!model) {
      return;
    }
    const previewMode = previewModeByResultId[model.resultId] === 'edited' && model.editedVariant?.baseColorUrl
      ? 'edited'
      : 'meshy';
    const baseColorTextureUrl =
      previewMode === 'edited' ? model.editedVariant?.baseColorUrl : model.textureMaps?.baseColor;
    if (!baseColorTextureUrl) {
      return;
    }
    const workspaceId = getTextureWorkspaceId(baseModel?.baseModelId ?? null, model);
    setSelectedTexturedResultId(model.resultId);
    setActiveTextureWorkspaceId(workspaceId);
    const nextRequestId = ++canvasInsertRequestRef.current;
    setCanvasTextureLayer({
      requestId: nextRequestId,
      workspaceId,
      imageUrl: baseColorTextureUrl,
      label: model?.title ? `${model.title} 底图层` : 'meshy-base-color-texture-layer',
    });
  }, [baseModel?.baseModelId, previewModeByResultId, texturedModels]);

  const handleGeneratePatternPreview = useCallback(async () => {
    if (!token || !sessionId || !selectedTexturedModel || !selectedPatternTextureUrl) {
      return;
    }

    try {
      setPatternGenerating(true);
      setJoinError(null);
      setPatternPreviewItem(null);
      const canvasSnapshotDataUrl = designerCanvasRef.current?.exportVisibleCanvasDataUrl() ?? null;
      const preview = await generateTexturePattern(token, {
        sessionId,
        resultId: selectedTexturedModel.resultId,
        previewMode: selectedTexturePreviewMode,
        workspaceId: activeTextureWorkspaceId,
        patternPromptText,
        canvasSnapshotDataUrl,
      });
      setPatternPreviewItem(preview);
      setPatternPopoverOpen(true);
    } catch (error) {
      setJoinError(parseApiError(error, '生成自动图案失败。'));
    } finally {
      setPatternGenerating(false);
    }
  }, [
    activeTextureWorkspaceId,
    patternPromptText,
    selectedPatternTextureUrl,
    selectedTexturedModel,
    selectedTexturePreviewMode,
    sessionId,
    token,
  ]);

  const handleInsertPatternPreview = useCallback(() => {
    if (!patternPreviewItem) {
      return;
    }
    const nextRequestId = ++canvasInsertRequestRef.current;
    setCanvasInsertAsset({
      requestId: nextRequestId,
      imageUrl: patternPreviewItem.item.imageUrl,
        label: 'AI 图案素材',
    });
    setPatternPopoverOpen(false);
  }, [patternPreviewItem]);

  const handleDuplicateCanvasSelection = useCallback(() => {
    void designerCanvasRef.current?.duplicateActiveSelection();
  }, []);

  const handleApplyEditedTexture = useCallback(
    async (payload: { workspaceId: string; dataUrl: string }) => {
      if (!token || !sessionId || !selectedTexturedModel || payload.workspaceId !== activeTextureWorkspaceId) {
        return;
      }

      try {
        setApplyTexturePending(true);
        setJoinError(null);
        const editedBaseColorFile = toPngFileFromDataUrl(
          payload.dataUrl,
          `${selectedTexturedModel.resultId}_edited_base_color.png`,
        );
        const nextState = await applyEditedTexture(token, {
          sessionId,
          resultId: selectedTexturedModel.resultId,
          editedBaseColorFile,
        });
        const updatedModel =
          nextState.models.find((model) => model.resultId === selectedTexturedModel.resultId) ?? selectedTexturedModel;
        setTextureModelsStatus(nextState.status);
        setTexturedModels(nextState.models);
        setSelectedTexturedResultId(updatedModel.resultId);
        setPreviewModeByResultId((current) => ({
          ...current,
          [updatedModel.resultId]: 'edited',
        }));
      } catch (error) {
        setJoinError(parseApiError(error, '回贴编辑纹理失败。'));
      } finally {
        setApplyTexturePending(false);
      }
    },
    [activeTextureWorkspaceId, selectedTexturedModel, sessionId, token],
  );

  const handleRefreshReview = useCallback(
    async (resultId: string) => {
      if (!token || !sessionId || !resultId) {
        return null;
      }

      try {
        setRefreshReviewPendingResultId(resultId);
        setJoinError(null);
        const nextState = await refreshTextureModelReview(token, {
          sessionId,
          resultId,
        });
        setTextureModelsStatus(nextState.status);
        setTexturedModels(nextState.models);
        if (uiStage >= 3) {
          void syncMeetingSharedReviewModels();
        }
        return nextState;
      } catch (error) {
        setJoinError(parseApiError(error, '刷新阶段三评审失败。'));
        return null;
      } finally {
        setRefreshReviewPendingResultId(null);
      }
    },
      [sessionId, syncMeetingSharedReviewModels, token, uiStage],
    );

  const handleCloseStage2Comment = useCallback((role: Stage2ReviewRole) => {
    setStage2CommentPanels((current) => ({
      ...current,
      [role]: {
        ...current[role],
        open: false,
        loading: false,
        error: null,
      },
    }));
  }, []);

  const handleOpenStage2Comment = useCallback(
    async (role: Stage2ReviewRole) => {
      if (uiStage !== 2 || !selectedTexturedModel || selectedTexturedModel.status !== 'completed') {
        return;
      }

      const existingComment = getStage2QuickComment(selectedTexturedModel, role);
      if (existingComment) {
        setStage2CommentPanels((current) => ({
          ...current,
          [role]: {
            ...current[role],
            open: true,
            loading: false,
            error: null,
          },
        }));
        return;
      }

      setStage2CommentPanels((current) => ({
        ...current,
        [role]: {
          ...current[role],
          open: true,
          loading: true,
          error: null,
        },
      }));

      const nextState = await handleRefreshReview(selectedTexturedModel.resultId);
      const refreshedModel =
        nextState?.models.find((model) => model.resultId === selectedTexturedModel.resultId) ?? null;
      const refreshedComment = getStage2QuickComment(refreshedModel, role);

      setStage2CommentPanels((current) => ({
        ...current,
        [role]: {
          ...current[role],
          open: true,
          loading: false,
          error: refreshedComment ? null : '该方案暂无快速评论。',
        },
      }));
    },
    [handleRefreshReview, selectedTexturedModel, uiStage],
  );

  useEffect(() => {
    if (uiStage !== 2 || typeof window === 'undefined') {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.repeat ||
        meetingSettingsOpen ||
        sharedResultsViewerOpen ||
        isEditableEventTarget(event.target)
      ) {
        return;
      }

      const key = event.key.toLowerCase();
      if (key === 'f') {
        event.preventDefault();
        void handleOpenStage2Comment('engineering');
      } else if (key === 'g') {
        event.preventDefault();
        void handleOpenStage2Comment('passenger');
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleOpenStage2Comment, meetingSettingsOpen, sharedResultsViewerOpen, uiStage]);

  const handleOpenMeetingSettings = useCallback(async () => {
    setMeetingSettingsOpen(true);
    setMeetingSettingsLoading(true);
    try {
      if (token && sessionId) {
        await syncMeetingSettings();
      } else if (!meetingSettings) {
        setMeetingSettings(cloneMeetingSettings());
      }
    } catch (error) {
      setJoinError(parseApiError(error, '加载设置失败。'));
    } finally {
      setMeetingSettingsLoading(false);
    }
  }, [meetingSettings, sessionId, syncMeetingSettings, token]);

  const handleCloseMeetingSettings = useCallback(() => {
    setMeetingSettingsOpen(false);
    setMeetingSettingsLoading(false);
    if (token && sessionId) {
      void syncMeetingSettings();
    } else {
      setMeetingSettings(cloneMeetingSettings());
    }
  }, [sessionId, syncMeetingSettings, token]);

  const handleReviewRolesChange = useCallback((roles: ReviewPersonaRoleConfig[]) => {
    setMeetingSettings((current) => {
      const base = cloneMeetingSettings(current);
      const passengerRole = roles.find((role) => role.type === 'passenger' && role.enabled) ?? roles.find((role) => role.type === 'passenger');
      const engineeringRole = roles.find((role) => role.type === 'engineering' && role.enabled) ?? roles.find((role) => role.type === 'engineering');
      return {
        ...base,
        reviewPersonas: {
          ...base.reviewPersonas,
          passenger: passengerRole
            ? {
                displayName: passengerRole.displayName,
                identitySummary: passengerRole.identitySummary,
                preferenceTags: [...passengerRole.preferenceTags],
                dislikeTags: [...passengerRole.dislikeTags],
                focusPoints: [...passengerRole.focusPoints],
              }
            : base.reviewPersonas.passenger,
          engineering: engineeringRole
            ? {
                displayName: engineeringRole.displayName,
                identitySummary: engineeringRole.identitySummary,
                priorityTags: [...engineeringRole.priorityTags],
                riskFocus: [...engineeringRole.riskFocus],
                focusPoints: [...engineeringRole.focusPoints],
              }
            : base.reviewPersonas.engineering,
          roles: roles.map(cloneReviewRole),
        },
      };
    });
  }, []);

  const handleRestoreMeetingSettingsDefaults = useCallback(() => {
    setMeetingSettings((current) => {
      const base = cloneMeetingSettings(current);
      void activeMeetingSettingsSection;
      const defaults = cloneMeetingSettings();
      return {
        ...base,
        reviewPersonas: defaults.reviewPersonas,
      };
    });
  }, [activeMeetingSettingsSection]);

  const handleSaveMeetingSettings = useCallback(async () => {
    if (!token || !sessionId || !meetingSettings || !meetingSettingsPermissions?.canEdit || meetingSettingsSaving) {
      return;
    }
    try {
      setMeetingSettingsSaving(true);
      setJoinError(null);
      const next = await patchSessionSettings(token, sessionId, meetingSettings);
      setMeetingSettings(cloneMeetingSettings(next.sessionSettings));
      setMeetingSettingsPermissions(next.settingsPermissions);
      setMeetingSettingsSections(next.sections);
    } catch (error) {
      setJoinError(parseApiError(error, '保存设置失败。'));
    } finally {
      setMeetingSettingsSaving(false);
    }
  }, [meetingSettings, meetingSettingsPermissions?.canEdit, meetingSettingsSaving, sessionId, token]);

  const handleShareResults = useCallback(
    async (resultIds: string[]) => {
      if (!token || !sessionId) {
        return false;
      }
      try {
        setSharingResultsPending(true);
        setJoinError(null);
        await shareTextureResults(token, {
          sessionId,
          resultIds,
        });
        await syncSessionMembers();
        return true;
      } catch (error) {
        setJoinError(parseApiError(error, '发布选中方案失败。'));
        return false;
      } finally {
        setSharingResultsPending(false);
      }
    },
    [sessionId, syncSessionMembers, token],
  );

  const handleOpenSharedResultsViewer = useCallback(
    async (participant: SessionMemberDirectoryEntry) => {
      if (!token || !sessionId) {
        return;
      }
      try {
        setJoinError(null);
        setSharedResultsViewerOpen(true);
        setSharedResultsViewerLoading(true);
        setSharedResultsViewerImporting(false);
        setSharedResultsViewerSourceUserId(participant.userId);
        setSharedResultsViewerSourceUserName(participant.name);
        setSharedResultsViewerSelectedResultIds([]);
        const response = await fetchSharedTextureResults(token, {
          sessionId,
          sourceUserId: participant.userId,
        });
        setSharedResultsViewerSourceUserId(response.sourceUserId);
        setSharedResultsViewerSourceUserName(response.sourceUserName);
        setSharedResultsViewerModels(response.models);
        setSharedResultsViewerHighlightedResultId(response.models[0]?.resultId ?? null);
      } catch (error) {
        setSharedResultsViewerOpen(false);
        setJoinError(parseApiError(error, '加载共享方案失败。'));
      } finally {
        setSharedResultsViewerLoading(false);
      }
    },
    [sessionId, token],
  );

  const handleParticipantLiveSync = useCallback(
    (participant: SessionMemberDirectoryEntry) => {
      if (uiStage !== 2) {
        setJoinError('实时同步仅可在阶段二设计画布使用。');
        return;
      }
      void handleOpenSharedResultsViewer(participant);
    },
    [handleOpenSharedResultsViewer, uiStage],
  );

  const handleCloseSharedResultsViewer = useCallback(() => {
    setSharedResultsViewerOpen(false);
    setSharedResultsViewerLoading(false);
    setSharedResultsViewerImporting(false);
    setSharedResultsViewerSourceUserId(null);
    setSharedResultsViewerSourceUserName('');
    setSharedResultsViewerModels([]);
    setSharedResultsViewerHighlightedResultId(null);
    setSharedResultsViewerSelectedResultIds([]);
  }, []);

  useEffect(() => {
    if (uiStage !== 2 && sharedResultsViewerOpen) {
      handleCloseSharedResultsViewer();
    }
  }, [handleCloseSharedResultsViewer, sharedResultsViewerOpen, uiStage]);

  const handleToggleSharedImportSelection = useCallback((resultId: string) => {
    setSharedResultsViewerSelectedResultIds((current) =>
      current.includes(resultId) ? current.filter((item) => item !== resultId) : [...current, resultId],
    );
  }, []);

  const handleImportSharedResults = useCallback(async () => {
    if (!token || !sessionId || !sharedResultsViewerSourceUserId || sharedResultsViewerSelectedResultIds.length === 0) {
      return;
    }
    try {
      setSharedResultsViewerImporting(true);
      setJoinError(null);
      const nextState = await importSharedTextureResults(token, {
        sessionId,
        sourceUserId: sharedResultsViewerSourceUserId,
        resultIds: sharedResultsViewerSelectedResultIds,
      });
      setTextureModelsStatus(nextState.status);
      setTexturedModels(nextState.models);
      const importedModel = [...nextState.models]
        .reverse()
        .find(
          (model) =>
            model.sourceType === 'imported' &&
            model.sharedOrigin?.userId === sharedResultsViewerSourceUserId &&
            sharedResultsViewerSelectedResultIds.includes(model.sharedOrigin.sourceResultId),
        );
      if (importedModel) {
        setSelectedTexturedResultId(importedModel.resultId);
      }
      handleCloseSharedResultsViewer();
    } catch (error) {
      setJoinError(parseApiError(error, '导入共享方案失败。'));
    } finally {
      setSharedResultsViewerImporting(false);
    }
  }, [
    handleCloseSharedResultsViewer,
    sessionId,
    sharedResultsViewerSelectedResultIds,
    sharedResultsViewerSourceUserId,
    token,
  ]);

  const handleWorkspaceContentChange = useCallback((workspaceId: string, hasContent: boolean) => {
    setWorkspaceHasContent((current) => {
      if (current[workspaceId] === hasContent) {
        return current;
      }
      return {
        ...current,
        [workspaceId]: hasContent,
      };
    });
  }, []);

  const activeWorkspaceHasContent = workspaceHasContent[activeTextureWorkspaceId] ?? false;

  const renderMeetingStage = () => {
    if (uiStage === 1) {
      return (
        <div className="flex h-full min-h-0 overflow-hidden">
          <AppErrorBoundary title="阶段一渲染失败">
            <Stage1PlanningView
              isHost={isHost}
              backendStage={backendStage}
              modelTaskStatus={modelTaskStatus}
              modelTaskProgress={modelTaskProgress}
              modelPipelineStage={modelPipelineStage}
              modelProgressMessage={modelProgressMessage}
              preparingBaseModel={modelPreparing}
              designGoal={designGoal}
              onDesignGoalChange={setDesignGoal}
              productCategory={productCategory}
              onProductCategoryChange={setProductCategory}
              modelSource={modelSource}
              onModelSourceChange={setModelSource}
              productProfile={productProfile}
              onProductProfileChange={setProductProfile}
              brief={brief}
              onParseBrief={() => {
                void handleParseBrief();
              }}
              baseModel={baseModel}
              baseModelLocked={baseModelLocked}
              onLockBaseModel={() => {
                void handleLockBaseModel();
              }}
              onUploadFileSelected={handleUploadFileSelected}
              uploadedFileName={uploadedModelFile?.name ?? baseModel?.mappingMeta?.inspection?.fileName ?? null}
            />
          </AppErrorBoundary>
          <ParticipantSidebar
            participants={visibleParticipants}
            currentUserId={currentUserId}
            onLiveSync={handleParticipantLiveSync}
            collapsible
            defaultCollapsed
          />
        </div>
      );
    }

    if (uiStage === 2) {
      return (
        <div className="relative flex h-full min-h-0 overflow-hidden">
          <TexturePlanningSidebar
            token={token}
            sessionId={sessionId}
            brief={brief}
            baseModel={baseModel}
            texturePlan={texturePlan}
            loading={texturePlanLoading}
            generating={texturePlanGenerating}
            saving={texturePlanSaving}
            imageAnalyzing={textureImageAnalyzing}
            onAnalyzeReferenceImage={handleAnalyzeTextureImage}
            onGenerateModelTextures={handleGenerateModelTextures}
            onUpdateSelectedImageKeywords={handleUpdateSelectedImageKeywords}
            onRemoveDocument={handleRemoveTextureDocument}
            onRemoveImage={handleRemoveTextureImage}
          />
          <section className="flex min-w-0 flex-1 basis-0 flex-col">
            <header className="relative z-20 flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-2">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                {TOOL_OPTIONS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setTool(item.id)}
                    className={`inline-flex h-9 items-center gap-1.5 rounded-xl px-2.5 text-[9px] font-bold uppercase tracking-[0.14em] transition-all ${
                      tool === item.id
                        ? 'bg-blue-600 text-white shadow-md scale-[1.05]'
                        : 'bg-white text-slate-500 hover:bg-slate-50 border border-slate-200'
                    }`}
                  >
                    {item.icon}
                    {item.label}
                  </button>
                ))}

                <div className="relative">
                  <button
                    type="button"
                    title="自动图案"
                    onClick={() => setPatternPopoverOpen((current) => !current)}
                    disabled={!canGeneratePattern}
                    className={`inline-flex h-9 w-9 items-center justify-center rounded-xl border transition-all ${
                      patternPopoverOpen
                        ? 'border-blue-200 bg-blue-50 text-blue-600 shadow-sm'
                        : canGeneratePattern
                          ? 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                          : 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-300'
                    }`}
                  >
                    {patternGenerating ? <LoaderCircle size={15} className="animate-spin" /> : <Sparkles size={15} />}
                  </button>
                  {patternPopoverOpen ? (
                    <div className="absolute left-0 top-full z-30 mt-2 max-h-[78vh] w-[320px] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3 shadow-xl">
                      <div className="mb-3 flex items-start justify-between gap-3">
                        <div>
                          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">自动图案</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setPatternPopoverOpen(false)}
                          className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                          aria-label="关闭图案面板"
                        >
                          <X size={14} />
                        </button>
                      </div>

                      <textarea
                        value={patternPromptText}
                        onChange={(event) => setPatternPromptText(event.target.value)}
                        placeholder="描述图案方向"
                        rows={3}
                        className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-blue-300 focus:bg-white focus:ring-2 focus:ring-blue-100"
                      />

                      <div className="mt-3 flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            void handleGeneratePatternPreview();
                          }}
                          disabled={!canGeneratePattern || patternGenerating}
                          className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition ${
                            canGeneratePattern && !patternGenerating
                              ? 'bg-blue-600 text-white hover:bg-blue-700'
                              : 'cursor-not-allowed bg-slate-100 text-slate-400'
                          }`}
                        >
                          {patternGenerating ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />}
                          {patternPreviewItem ? '重新生成' : '生成'}
                        </button>
                        {!canGeneratePattern ? (
                          <span className="text-[11px] text-slate-400">先选择纹理</span>
                        ) : null}
                      </div>

                      {patternPreviewItem ? (
                        <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-[11px] font-semibold text-slate-600">预览</p>
                            <div className="flex items-center gap-1">
                              {patternPreviewItem.dominantColors.slice(0, 4).map((color) => (
                                <span
                                  key={color}
                                  className="inline-block h-3 w-3 rounded-full border border-white shadow-sm"
                                  style={{ backgroundColor: color }}
                                  title={color}
                                />
                              ))}
                            </div>
                          </div>
                          <div className="mt-2 flex items-center justify-center rounded-xl border border-dashed border-slate-200 bg-[radial-gradient(circle_at_1px_1px,_rgba(148,163,184,0.18)_1px,_transparent_0)] bg-[size:12px_12px] p-3">
                            <img
                              src={patternPreviewItem.item.imageUrl}
                              alt="生成图案预览"
                              className="max-h-32 max-w-full object-contain"
                            />
                          </div>
                          <button
                            type="button"
                            onClick={handleInsertPatternPreview}
                            className="sticky bottom-0 mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-slate-800"
                          >
                            <ImagePlus size={14} />
                            插入画布
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <button
                  type="button"
                  title="复制选中对象 (Ctrl/Cmd + D)"
                  onClick={handleDuplicateCanvasSelection}
                  disabled={!canvasHasSelection}
                  className={`inline-flex h-9 w-9 items-center justify-center rounded-xl border transition-all ${
                    canvasHasSelection
                      ? 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                      : 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-300'
                  }`}
                >
                  <Copy size={15} />
                </button>

                <div className="mx-0.5 hidden h-4 w-px bg-slate-200 xl:block" />
                <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500 transition-colors hover:bg-slate-50 shadow-sm">
                  <Brush size={11} className="text-blue-500" />
                  描边
                  <input
                    type="color"
                    title="画笔颜色"
                    value={strokeColor}
                    onChange={(event) => setStrokeColor(event.target.value)}
                    className="h-4 w-4 cursor-pointer overflow-hidden rounded-full border-0 bg-transparent p-0"
                  />
                </label>
                <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500 transition-colors hover:bg-slate-50 shadow-sm">
                  填充
                  <input
                    type="color"
                    title="填充颜色"
                    value={fillColor}
                    onChange={(event) => setFillColor(event.target.value)}
                    className="h-4 w-4 cursor-pointer overflow-hidden rounded-full border-0 bg-transparent p-0"
                  />
                </label>
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-slate-400">
                  <Save size={11} className={lastAutoSavedAt ? 'text-emerald-500' : ''} />
                  {lastAutoSavedAt ? `已保存 ${lastAutoSavedAt}` : '未保存'}
                </span>
              </div>
            </header>

            <div className="min-h-0 flex-1">
              <DesignerCanvas
                ref={designerCanvasRef}
                tool={tool}
                sessionId={sessionId}
                schemeId={activeTextureWorkspaceId}
                strokeColor={strokeColor}
                fillColor={fillColor}
                baseModelId={baseModel?.baseModelId ?? null}
                storageUserKey={currentStorageUserKey}
                uvTemplateUrl={baseModel?.uvTemplateUrl ?? null}
                uvTemplateMode={baseModel?.mappingMeta?.inspection?.uvTemplateMode ?? null}
                textureCanvasSize={textureCanvasSize}
                linkedUvFocus={linkedUvFocus}
                onUvInspect={setLinkedUvFocus}
                onAutoSave={handleAutoSave}
                baseTextureLayer={canvasTextureLayer}
                insertAsset={canvasInsertAsset}
                showApplyEditedTexture={Boolean(selectedTexturedModel?.textureMaps?.baseColor || selectedTexturedModel?.editedVariant?.baseColorUrl)}
                canApplyEditedTexture={Boolean(selectedTexturedModel) && activeWorkspaceHasContent}
                applyEditedTexturePending={applyTexturePending}
                onApplyEditedTexture={handleApplyEditedTexture}
                onWorkspaceContentChange={handleWorkspaceContentChange}
                onSelectionChange={setCanvasHasSelection}
              />
            </div>
          </section>
          <Stage2LinkedPreview
            baseModel={baseModel}
            token={token}
            sessionId={sessionId}
            canUploadCustomResult={canModifyWorkspace}
            linkedUvFocus={linkedUvFocus}
            onLinkedUvFocusChange={setLinkedUvFocus}
            texturedModels={texturedModels}
            textureModelsStatus={textureModelsStatus}
            selectedTexturedResultId={selectedTexturedResultId}
            selectedPreviewMode={selectedTexturePreviewMode}
            selectedTexturedModelUrl={selectedTexturedPreviewUrl}
            onSelectTexturedModel={handleSelectTexturedModel}
            onAddTextureToCanvas={handleAddTextureToCanvas}
            deletingResultId={deletingTexturedResultId}
            onDeleteTexturedModel={canModifyWorkspace ? handleDeleteTexturedModel : undefined}
            onUploadCustomTexturedModel={canModifyWorkspace ? handleUploadCustomTexturedModel : undefined}
            ownSharedResultIds={ownSharedResultIds}
            sharingResultsPending={sharingResultsPending}
            onShareResults={canModifyWorkspace ? handleShareResults : undefined}
            sharedResultsViewer={{
              open: sharedResultsViewerOpen,
              sourceUserName: sharedResultsViewerSourceUserName,
              models: sharedResultsViewerModels,
              highlightedResultId: sharedResultsViewerHighlightedResultId,
              selectedResultIds: sharedResultsViewerSelectedResultIds,
              loading: sharedResultsViewerLoading,
              importing: sharedResultsViewerImporting,
            }}
            onCloseSharedResultsViewer={handleCloseSharedResultsViewer}
            onHighlightSharedResult={setSharedResultsViewerHighlightedResultId}
            onToggleSharedResultSelection={handleToggleSharedImportSelection}
            onImportSharedResults={() => {
              void handleImportSharedResults();
            }}
            onPreviewModeChange={(mode) => {
              if (!selectedTexturedModel) {
                return;
              }
              setPreviewModeByResultId((current) => ({
                ...current,
                [selectedTexturedModel.resultId]: mode,
              }));
            }}
            reviewCommentStates={stage2ReviewCommentStates}
            onCloseReviewComment={handleCloseStage2Comment}
          />
          <ParticipantSidebar
            participants={visibleParticipants}
            currentUserId={currentUserId}
            onLiveSync={handleParticipantLiveSync}
            collapsible
            defaultCollapsed
          />
        </div>
      );
    }

    if (uiStage === 3) {
      return (
        <div className="relative flex h-full min-h-0 overflow-hidden">
          <Stage3ReviewView
            schemes={reviewSchemes}
            baseModel={baseModel}
            token={token}
            sessionId={sessionId}
            isHost={isHost}
            currentUserId={currentUserIdString}
            onStarScheme={handleStarScheme}
            onRefreshReview={(resultId) => {
              void handleRefreshReview(resultId);
            }}
            refreshingReviewSchemeId={refreshReviewPendingResultId}
          />
          <ParticipantSidebar
            participants={visibleParticipants}
            currentUserId={currentUserId}
            onLiveSync={handleParticipantLiveSync}
            collapsible
            defaultCollapsed
          />
        </div>
      );
    }

    return (
      <div className="relative flex h-full min-h-0 overflow-hidden">
        <Stage4PreviewView
          schemes={reviewSchemes}
          baseModel={baseModel}
          token={token}
          sessionId={sessionId}
          soundEnabled={listeningEnabled}
        />
      </div>
    );
  };

  if (screen === 'entry') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-100 via-blue-50 to-slate-200 p-4">
        <div className="w-full max-w-md rounded-[2.5rem] border border-slate-200 bg-white p-10 shadow-xl">
          <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-blue-600">协作设计系统</p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tighter text-slate-800">Co-Track</h1>
          <div className="mt-5 space-y-3">
            <label className="block text-sm text-slate-700">
              姓名
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="例如 Alice"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </label>

            <label className="block text-sm text-slate-700">
              邀请码
              <input
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value.trim())}
                placeholder="555555"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </label>

            <label className="block">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">项目角色</span>
              <select
                value={selectedRole}
                onChange={(event) => setSelectedRole(event.target.value as MeetingRole)}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700 outline-none transition focus:border-blue-400 focus:bg-white"
              >
                <option value="host">主持人</option>
                <option value="designer">设计师</option>
                <option value="observer">观察员</option>
              </select>
            </label>
          </div>

          {joinError ? (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <AlertCircle size={14} className="mt-0.5" />
              <span>{joinError}</span>
            </div>
          ) : null}

          <button
            type="button"
            onClick={handleEnterPreJoin}
            className="mt-10 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-blue-600 px-4 py-4 text-[13px] font-bold uppercase tracking-[0.1em] text-white transition-all hover:bg-blue-700 hover:shadow-lg active:scale-[0.98]"
          >
            <LogIn size={16} />
            进入
            <ArrowRight size={16} />
          </button>
        </div>
      </main>
    );
  }

  if (screen === 'prejoin') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
        <div className="w-full max-w-3xl space-y-3">
          {joinError ? (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <AlertCircle size={14} className="mt-0.5" />
              <span>{joinError}</span>
            </div>
          ) : null}
          <PreJoinPanel
            role={selectedRole}
            onRoleChange={setSelectedRole}
            onBack={() => setScreen('entry')}
            onJoin={handleJoinMeeting}
            joining={joining}
          />
        </div>
      </main>
    );
  }

    return (
      <div className="flex h-screen flex-col bg-slate-100">
        <header className="border-b border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div className="grid grid-cols-3 items-center gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <p className="truncate text-sm font-semibold text-slate-800">{sessionName || '未命名协作空间'}</p>
              <button
                type="button"
                onClick={() => {
                  void handleOpenMeetingSettings();
                }}
                title="设置"
                aria-label="设置"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
              >
                <Settings2 size={15} />
              </button>
            </div>

            <div className="flex items-center justify-center gap-1.5">
              {STAGE_ORDER.map((stage) => (
                <div key={stage} className="flex items-center gap-1.5">
                  <span
                    className={`rounded-full px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.1em] whitespace-nowrap transition-all duration-300 ${
                      stage <= uiStage ? 'bg-blue-600 text-white shadow-sm' : 'bg-slate-100 text-slate-400'
                    }`}
                  >
                    {HEADER_STAGE_LABELS[stage]}
                  </span>
                  {stage < 4 && <div className="h-px w-2.5 bg-slate-200" />}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-end gap-2 min-w-0">
              <button
                type="button"
                onClick={() => setListeningEnabled((current) => !current)}
                title={listeningEnabled ? '关闭他人声音' : '打开他人声音'}
                aria-label={listeningEnabled ? '关闭他人声音' : '打开他人声音'}
                aria-pressed={listeningEnabled}
                className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border transition hover:border-slate-300 hover:bg-slate-50 ${
                  listeningEnabled
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-slate-200 bg-white text-slate-600'
                }`}
              >
                {listeningEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
              </button>

              <button
                type="button"
                onClick={() => {
                  void rtc.toggleAudio();
                }}
                disabled={!rtc.canPublishMedia}
                title={
                  !rtc.canPublishMedia
                    ? '需要发言权限后才能打开麦克风'
                    : rtc.audioEnabled
                      ? '关闭我的麦克风'
                      : '打开我的麦克风'
                }
                aria-label={
                  !rtc.canPublishMedia
                    ? '需要发言权限后才能打开麦克风'
                    : rtc.audioEnabled
                      ? '关闭我的麦克风'
                      : '打开我的麦克风'
                }
                aria-pressed={rtc.audioEnabled}
                className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${
                  rtc.audioEnabled
                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                    : 'border-slate-200 bg-white text-slate-600'
                }`}
              >
                {rtc.audioEnabled ? <Mic size={15} /> : <MicOff size={15} />}
              </button>

              <button
                type="button"
                onClick={() => {
                  void rtc.toggleVideo();
                }}
                disabled={!rtc.canPublishMedia}
                title={
                  !rtc.canPublishMedia
                    ? '需要发言权限后才能打开摄像头'
                    : rtc.videoEnabled
                      ? '关闭我的摄像头'
                      : '打开我的摄像头'
                }
                aria-label={
                  !rtc.canPublishMedia
                    ? '需要发言权限后才能打开摄像头'
                    : rtc.videoEnabled
                      ? '关闭我的摄像头'
                      : '打开我的摄像头'
                }
                aria-pressed={rtc.videoEnabled}
                className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${
                  rtc.videoEnabled
                    ? 'border-cyan-200 bg-cyan-50 text-cyan-700'
                    : 'border-slate-200 bg-white text-slate-600'
                }`}
              >
                {rtc.videoEnabled ? <Video size={15} /> : <VideoOff size={15} />}
              </button>

              {isHost && uiStage > 1 ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleRevertStage();
                  }}
                  disabled={stageReverting}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-[11px] font-bold uppercase tracking-widest text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
                >
                  <span
                    aria-hidden
                    className={`h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-500 border-t-transparent ${
                      stageReverting ? '' : 'hidden'
                    }`}
                  />
                  {!stageReverting && <ArrowRight size={14} className="rotate-180" />}
                  返回
                </button>
              ) : null}

              {isHost && uiStage < 4 ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleAdvanceStage();
                  }}
                  disabled={stageAdvancing}
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-[11px] font-bold uppercase tracking-widest text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
                >
                  <span
                    aria-hidden
                    className={`h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent ${
                      stageAdvancing ? '' : 'hidden'
                    }`}
                  />
                  {!stageAdvancing && <ArrowRight size={14} />}
                  {uiStage === 3 ? '定稿' : '下一步'}
                </button>
              ) : null}

              <button
                type="button"
                onClick={handleLeaveMeeting}
                title="离开"
                aria-label="离开"
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-rose-200 bg-rose-50 text-rose-700 transition hover:border-rose-300 hover:bg-rose-100"
              >
                <LogOut size={14} />
              </button>
            </div>
          </div>

          {joinError ? (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <AlertCircle size={14} className="mt-0.5" />
              <span>{joinError}</span>
            </div>
          ) : null}
        </header>

        <MeetingSettingsModal
          open={meetingSettingsOpen}
          loading={meetingSettingsLoading}
          saving={meetingSettingsSaving}
          settings={meetingSettings}
          permissions={meetingSettingsPermissions}
          sections={meetingSettingsSections}
          activeSectionId={activeMeetingSettingsSection}
          onSelectSection={setActiveMeetingSettingsSection}
          onClose={handleCloseMeetingSettings}
          onRolesChange={handleReviewRolesChange}
          onSave={handleSaveMeetingSettings}
          onRestoreDefaults={handleRestoreMeetingSettingsDefaults}
        />

        {rtc.peers.map((peer) => (
          <RemoteAudioSink key={peer.userId} peer={peer} listeningEnabled={listeningEnabled} />
        ))}

      <div className="min-h-0 flex-1">{renderMeetingStage()}</div>
    </div>
  );
};

export default App;
