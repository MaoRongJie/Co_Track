import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Brush,
  Circle,
  Eraser,
  LogIn,
  PenTool,
  RectangleHorizontal,
  Save,
  Send,
  Slash,
} from 'lucide-react';
import AppErrorBoundary from './components/AppErrorBoundary.tsx';
import DesignerCanvas from './components/DesignerCanvas.tsx';
import MeetingDock from './components/MeetingDock.tsx';
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
  fetchSessionBaseModel,
  fetchSessionDetail,
  applyEditedTexture,
  fetchTextureModels,
  fetchTexturePlan,
  getApiBaseUrl,
  joinSessionByInvite,
  patchTexturePlan,
  parseApiError,
  parseBrief,
  revertSessionStage,
  selectBaseModel,
  startGenerateModelTextures,
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
import type { AuthUser, MeetingRole, PreJoinSettings, SessionStage } from './types/meeting.ts';
import { buildReviewSchemes } from './utils/reviewScoring.ts';

type AppScreen = 'entry' | 'prejoin' | 'meeting';
type UiStage = 1 | 2 | 3 | 4;
type TexturePreviewMode = 'meshy' | 'edited';
type PersistedTextureWorkspaceState = {
  selectedTexturedSchemeId: string | null;
  activeTextureWorkspaceId: string;
  previewModeByScheme: Record<string, TexturePreviewMode>;
  canvasTextureLayer: {
    workspaceId: string;
    imageUrl: string;
    label?: string;
  } | null;
};

const DEFAULT_PASSWORD = 'CoTrack@123456';
const DEFAULT_DESIGN_GOAL = 'Winter theme, blue-white palette, snowflake element, speed feeling';
const DEFAULT_PRODUCT_CATEGORY: ProductCategory = 'high_speed_train';
const DEFAULT_PRODUCT_PROFILE: ProductProfile = {
  series: 'CR400AF',
  formation: '8 cars',
  totalLengthM: 208.95,
  maxWidthMm: 3360,
  maxHeightMm: 3700,
};

const STAGE_LABELS: Record<UiStage, string> = {
  1: 'Stage 1 Target Setup',
  2: 'Stage 2 Design Canvas',
  3: 'Stage 3 Review',
  4: 'Stage 4 Preview',
};
const STAGE_ORDER: UiStage[] = [1, 2, 3, 4];

const TOOL_OPTIONS: Array<{ id: CanvasTool; label: string; icon: React.ReactNode }> = [
  { id: 'select', label: 'Select', icon: <Slash size={14} /> },
  { id: 'pencil', label: 'Pencil', icon: <PenTool size={14} /> },
  { id: 'rect', label: 'Rect', icon: <RectangleHorizontal size={14} /> },
  { id: 'ellipse', label: 'Ellipse', icon: <Circle size={14} /> },
  { id: 'line', label: 'Line', icon: <Send size={14} /> },
  { id: 'eraser', label: 'Eraser', icon: <Eraser size={14} /> },
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
  model: Pick<TexturedModel, 'schemeId' | 'meshyTaskId'> | null,
): string => {
  const safeBaseModelId = baseModelId ?? 'no-model';
  if (!model) {
    return `workspace:${safeBaseModelId}:base`;
  }
  const stableToken = model.meshyTaskId || model.schemeId;
  return `workspace:${safeBaseModelId}:${stableToken}`;
};

const readStoredText = (storageKey: string, fallback: string): string => {
  if (typeof window === 'undefined') {
    return fallback;
  }
  const stored = window.localStorage.getItem(storageKey);
  return stored && stored.trim().length > 0 ? stored : fallback;
};

const getTextureWorkspaceStorageKey = (sessionId: number | null, baseModelId: number | null): string =>
  `co-track:texture-ui:${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}`;

const getCanvasSnapshotStorageKey = (
  sessionId: number | null,
  baseModelId: number | null,
  schemeId: string,
): string => `co-track:snapshot:${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}:${schemeId}`;

const getReviewStarStorageKey = (sessionId: number | null): string =>
  `co-track:review-stars:${sessionId ?? 'no-session'}`;

const cloneDefaultProductProfile = (): ProductProfile => ({ ...DEFAULT_PRODUCT_PROFILE });

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

const clearSessionWorkspaceCache = (sessionId: number | null) => {
  if (typeof window === 'undefined' || !sessionId) {
    return;
  }
  const prefixes = [
    `co-track:texture-ui:${sessionId}:`,
    `co-track:snapshot:${sessionId}:`,
    `co-track:review-stars:${sessionId}`,
  ];
  const keysToDelete: string[] = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const storageKey = window.localStorage.key(index);
    if (!storageKey) {
      continue;
    }
    if (prefixes.some((prefix) => storageKey.startsWith(prefix))) {
      keysToDelete.push(storageKey);
    }
  }
  keysToDelete.forEach((storageKey) => window.localStorage.removeItem(storageKey));
};

const readPersistedReviewStars = (sessionId: number | null): Record<string, string[]> => {
  if (typeof window === 'undefined' || !sessionId) {
    return {};
  }
  const raw = window.localStorage.getItem(getReviewStarStorageKey(sessionId));
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
): PersistedTextureWorkspaceState | null => {
  if (typeof window === 'undefined' || !sessionId) {
    return null;
  }
  const raw = window.localStorage.getItem(getTextureWorkspaceStorageKey(sessionId, baseModelId));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedTextureWorkspaceState> | null;
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }

    const previewModeByScheme = Object.fromEntries(
      Object.entries(parsed.previewModeByScheme ?? {}).filter(
        ([schemeId, mode]) =>
          typeof schemeId === 'string' && schemeId.length > 0 && (mode === 'meshy' || mode === 'edited'),
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
      selectedTexturedSchemeId:
        typeof parsed.selectedTexturedSchemeId === 'string' || parsed.selectedTexturedSchemeId === null
          ? parsed.selectedTexturedSchemeId
          : null,
      activeTextureWorkspaceId:
        typeof parsed.activeTextureWorkspaceId === 'string' && parsed.activeTextureWorkspaceId.length > 0
          ? parsed.activeTextureWorkspaceId
          : getTextureWorkspaceId(baseModelId, null),
      previewModeByScheme,
      canvasTextureLayer,
    };
  } catch {
    return null;
  }
};

const toPngFileFromDataUrl = (dataUrl: string, fileName: string): File => {
  const [header, body] = dataUrl.split(',', 2);
  if (!header || !body) {
    throw new Error('Canvas export did not return a valid PNG payload.');
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
  baseModelId: Math.max(0, Math.round(toSafeNumber(payload.id))),
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
  const [displayName, setDisplayName] = useState(() => readStoredText('co-track:display-name', 'Designer A'));
  const [inviteCode, setInviteCode] = useState(() => readStoredText('co-track:invite-code', '555555'));
  const [selectedRole, setSelectedRole] = useState<MeetingRole>('designer');
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  const [token, setToken] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [sessionName, setSessionName] = useState<string>('');
  const [backendStage, setBackendStage] = useState<SessionStage>('LOBBY');
  const [meetingRole, setMeetingRole] = useState<MeetingRole>('designer');

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
  const [selectedTexturedSchemeId, setSelectedTexturedSchemeId] = useState<string | null>(null);
  const [activeTextureWorkspaceId, setActiveTextureWorkspaceId] = useState<string>('workspace:no-model:base');
  const [previewModeByScheme, setPreviewModeByScheme] = useState<Record<string, TexturePreviewMode>>({});
  const [applyTexturePending, setApplyTexturePending] = useState(false);
  const [workspaceHasContent, setWorkspaceHasContent] = useState<Record<string, boolean>>({});
  const [canvasInsertAsset, setCanvasInsertAsset] = useState<{
    requestId: number;
    imageUrl: string;
    label?: string;
  } | null>(null);
  const [canvasTextureLayer, setCanvasTextureLayer] = useState<{
    requestId: number;
    workspaceId: string;
    imageUrl: string;
    label?: string;
  } | null>(null);
  const [starredSchemes, setStarredSchemes] = useState<Record<string, string[]>>({});

  const tokenRef = useRef<string | null>(null);
  const sessionIdRef = useRef<number | null>(null);
  const texturePlanWriteVersionRef = useRef(0);
  const canvasInsertRequestRef = useRef(0);

  const selectedTexturedModel = useMemo(
    () => texturedModels.find((model) => model.schemeId === selectedTexturedSchemeId) ?? null,
    [selectedTexturedSchemeId, texturedModels],
  );

  const currentUserId = currentUser ? String(currentUser.id) : '';

  const reviewSchemes = useMemo<ReviewScheme[]>(
    () =>
      buildReviewSchemes(texturedModels, baseModel).map((scheme) => ({
        ...scheme,
        starredBy: starredSchemes[scheme.schemeId] ?? [],
      })),
    [baseModel, starredSchemes, texturedModels],
  );

  const selectedTexturePreviewMode: TexturePreviewMode = useMemo(() => {
    if (!selectedTexturedModel) {
      return 'meshy';
    }
    const requestedMode = previewModeByScheme[selectedTexturedModel.schemeId];
    if (requestedMode === 'edited' && selectedTexturedModel.editedVariant?.modelUrl) {
      return 'edited';
    }
    return 'meshy';
  }, [previewModeByScheme, selectedTexturedModel]);

  const selectedTexturedPreviewUrl = useMemo(() => {
    if (!selectedTexturedModel) {
      return null;
    }
    if (selectedTexturePreviewMode === 'edited') {
      return selectedTexturedModel.editedVariant?.modelUrl ?? selectedTexturedModel.texturedModelUrl;
    }
    return selectedTexturedModel.texturedModelUrl;
  }, [selectedTexturedModel, selectedTexturePreviewMode]);

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
    const persistedTextureWorkspace = readPersistedTextureWorkspaceState(sessionId, baseModel?.baseModelId ?? null);
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
  }, [baseModel?.baseModelId, sessionId]);

  useEffect(() => {
    setStarredSchemes(readPersistedReviewStars(sessionId));
  }, [sessionId]);

  useEffect(() => {
    if (!selectedTexturedModel) {
      return;
    }
    setActiveTextureWorkspaceId(getTextureWorkspaceId(baseModel?.baseModelId ?? null, selectedTexturedModel));
  }, [baseModel?.baseModelId, selectedTexturedModel]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem('co-track:display-name', displayName);
  }, [displayName]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem('co-track:invite-code', inviteCode);
  }, [inviteCode]);

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionId) {
      return;
    }
    const payload: PersistedTextureWorkspaceState = {
      selectedTexturedSchemeId,
      activeTextureWorkspaceId,
      previewModeByScheme,
      canvasTextureLayer: canvasTextureLayer
        ? {
            workspaceId: canvasTextureLayer.workspaceId,
            imageUrl: canvasTextureLayer.imageUrl,
            label: canvasTextureLayer.label,
          }
        : null,
    };
    window.localStorage.setItem(
      getTextureWorkspaceStorageKey(sessionId, baseModel?.baseModelId ?? null),
      JSON.stringify(payload),
    );
  }, [
    activeTextureWorkspaceId,
    baseModel?.baseModelId,
    canvasTextureLayer,
    previewModeByScheme,
    selectedTexturedSchemeId,
    sessionId,
  ]);

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionId) {
      return;
    }
    window.localStorage.setItem(getReviewStarStorageKey(sessionId), JSON.stringify(starredSchemes));
  }, [sessionId, starredSchemes]);

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
      setSelectedTexturedSchemeId((current) => {
        if (current && nextTextureModels.models.some((model) => model.schemeId === current)) {
          return current;
        }
        const firstCompleted = nextTextureModels.models.find((model) => model.status === 'completed' && model.texturedModelUrl);
        return firstCompleted?.schemeId ?? null;
      });
      setPreviewModeByScheme((current) => {
        const next: Record<string, TexturePreviewMode> = {};
        for (const model of nextTextureModels.models) {
          const existingMode = current[model.schemeId];
          if (existingMode === 'edited' && model.editedVariant?.modelUrl) {
            next[model.schemeId] = 'edited';
            continue;
          }
          if (!existingMode && model.editedVariant?.modelUrl) {
            next[model.schemeId] = 'edited';
            continue;
          }
          next[model.schemeId] = 'meshy';
        }
        return next;
      });
    } catch {
      // ignore texture model sync failures
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
  }, [syncTextureModels]);

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
  });

  const isHost = meetingRole === 'host';

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

  const syncSessionBaseModel = useCallback(async () => {
    if (!tokenRef.current || !sessionIdRef.current) {
      return;
    }
    try {
      const baseModelState = await fetchSessionBaseModel(tokenRef.current, sessionIdRef.current);
      setBaseModel((current) => {
        if (baseModelState.baseModel) {
          return baseModelState.baseModel;
        }
        // Keep the locally prepared preview visible until the host explicitly locks a session base model.
        if (!baseModelState.modelLockedAt) {
          return current;
        }
        return null;
      });
      setBaseModelLocked(Boolean(baseModelState.modelLockedAt));
    } catch {
      // ignore sync failures in polling path
    }
  }, []);

  const handleEnterPreJoin = () => {
    if (displayName.trim().length === 0) {
      setJoinError('Please input your name.');
      return;
    }
    if (inviteCode.trim().length < 4) {
      setJoinError('Invite code is invalid.');
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
        const auth = await ensureUserToken(displayName, DEFAULT_PASSWORD);
        const joined = await joinSessionByInvite(auth.token, inviteCode, settings.role);
        const shouldClearSessionCache =
          joined.session.stage === 'LOBBY' &&
          !joined.session.base_model_id &&
          !joined.session.brief_json &&
          !(joined.session.design_goal_text && joined.session.design_goal_text.trim().length > 0);
        if (shouldClearSessionCache) {
          clearSessionWorkspaceCache(joined.session.id);
        }
        hydrateSessionStageState(joined.session);

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
              const persistedMode = persistedTextureWorkspace?.previewModeByScheme[model.schemeId];
              if (persistedMode === 'edited' && model.editedVariant?.modelUrl) {
                return [model.schemeId, 'edited'];
              }
              if (persistedMode === 'meshy') {
                return [model.schemeId, 'meshy'];
              }
              return [model.schemeId, model.editedVariant?.modelUrl ? 'edited' : 'meshy'];
            }),
          ) as Record<string, TexturePreviewMode>;
          const firstCompleted = nextTextureModels.models.find(
            (model) => model.status === 'completed' && model.texturedModelUrl,
          );
          const restoredSelectedTexturedSchemeId =
            persistedTextureWorkspace?.selectedTexturedSchemeId &&
            nextTextureModels.models.some((model) => model.schemeId === persistedTextureWorkspace.selectedTexturedSchemeId)
              ? persistedTextureWorkspace.selectedTexturedSchemeId
              : firstCompleted?.schemeId ?? null;
          const restoredSelectedModel =
            nextTextureModels.models.find((model) => model.schemeId === restoredSelectedTexturedSchemeId) ?? null;
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
          setSelectedTexturedSchemeId(restoredSelectedTexturedSchemeId);
          setPreviewModeByScheme(nextPreviewModes);
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
          setSelectedTexturedSchemeId(null);
          setPreviewModeByScheme({});
          setActiveTextureWorkspaceId(getTextureWorkspaceId(baseModelState.baseModel?.baseModelId ?? null, null));
          setCanvasTextureLayer(null);
        }
      } catch (error) {
        setJoinError(parseApiError(error, 'Failed to join meeting.'));
      } finally {
        setJoining(false);
      }
    },
    [displayName, hydrateSessionStageState, inviteCode],
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
    setSelectedTexturedSchemeId(null);
    setPreviewModeByScheme({});
    setApplyTexturePending(false);
    setWorkspaceHasContent({});
    setCanvasInsertAsset(null);
    setCanvasTextureLayer(null);
    setStarredSchemes({});
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
      setBackendStage(next.stage);
      setUiStage(mapBackendStageToUiStage(next.stage));
    } catch (error) {
      setJoinError(parseApiError(error, 'Failed to advance stage.'));
    } finally {
      setStageAdvancing(false);
    }
  }, [sessionId, stageAdvancing, token]);

  const handleRevertStage = useCallback(async () => {
    if (!token || !sessionId || stageReverting) {
      return;
    }

    try {
      setStageReverting(true);
      setJoinError(null);
      const next = await revertSessionStage(token, sessionId);
      hydrateSessionStageState(next);
      setBackendStage(next.stage);
      setUiStage(mapBackendStageToUiStage(next.stage));
      await Promise.all([syncSessionBaseModel(), syncTexturePlan(), syncTextureModels()]);
    } catch (error) {
      setJoinError(parseApiError(error, 'Failed to revert stage.'));
    } finally {
      setStageReverting(false);
    }
  }, [
    hydrateSessionStageState,
    sessionId,
    stageReverting,
    syncSessionBaseModel,
    syncTextureModels,
    syncTexturePlan,
    token,
  ]);

  const handleStarScheme = useCallback(
    (schemeId: string) => {
      if (!currentUserId) {
        return;
      }
      setStarredSchemes((current) => {
        const currentUsers = current[schemeId] ?? [];
        const nextUsers = currentUsers.includes(currentUserId)
          ? currentUsers.filter((userId) => userId !== currentUserId)
          : [...currentUsers, currentUserId];
        return {
          ...current,
          [schemeId]: nextUsers,
        };
      });
    },
    [currentUserId],
  );

  useEffect(() => {
    if (screen !== 'meeting' || !token || !sessionId) {
      return;
    }

    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const latest = await fetchSessionDetail(token, sessionId);
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
  }, [screen, sessionId, syncSessionBaseModel, syncTexturePlan, token]);

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
      setJoinError(parseApiError(error, 'Failed to parse brief.'));
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
      setModelProgressMessage('Upload received');
      setBaseModelLocked(false);

      if (modelSource !== 'upload') {
        throw new Error('Current version only supports Upload 3D Model.');
      }
      setUploadedModelFile(file);
      setBaseModel(null);
      setModelTaskStatus('uploading');
      setModelProgressMessage(`Uploading ${file.name}`);

      const uploaded = await uploadModel(token, sessionId, productCategory, file);
      setBackendStage('MODEL_PREPARING');
      setUiStage(1);
      setModelTaskStatus(uploaded.status);
      setModelTaskProgress(uploaded.progress);
      setModelPipelineStage(uploaded.pipelineStage);
      setModelProgressMessage('Queued for model processing');

      let readyModel: BaseModelMeta | null = null;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const task = await fetchModelTask(token, uploaded.taskId);
        setModelTaskStatus(task.status);
        setModelTaskProgress(task.progress);
        setModelPipelineStage(task.pipelineStage);
        setModelProgressMessage(task.progressMessage);

        if (task.status === 'failed') {
          throw new Error(task.errorMessage ?? 'Model processing failed.');
        }
        if (task.status === 'ready' && task.resultModel) {
          readyModel = task.resultModel;
          break;
        }
        await delay(1200);
      }

      if (!readyModel) {
        throw new Error('Model processing timed out.');
      }

      setBaseModel(readyModel);
      setBaseModelLocked(false);
    } catch (error) {
      setJoinError(parseApiError(error, 'Failed to prepare base model.'));
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
      setJoinError(parseApiError(error, 'Failed to lock base model.'));
    }
  }, [baseModel, isHost, sessionId, token]);

  const handleAutoSave = useCallback(
    (schemeId: string, snapshot: string) => {
      if (typeof window === 'undefined' || !sessionId) {
        return;
      }
      window.localStorage.setItem(
        getCanvasSnapshotStorageKey(sessionId, baseModel?.baseModelId ?? null, schemeId),
        snapshot,
      );
      setLastAutoSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    },
    [baseModel?.baseModelId, sessionId],
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
        setSelectedTexturedSchemeId(null);
        setPreviewModeByScheme({});
        setApplyTexturePending(false);
        setActiveTextureWorkspaceId(getTextureWorkspaceId(baseModel?.baseModelId ?? null, null));
        setCanvasTextureLayer(null);
        setTextureModelsStatus('queued');
        setTexturedModels([
          {
            schemeId: 'scheme_1',
            title: 'Queued',
            promptText: '',
            status: 'pending',
            texturedModelUrl: null,
            textureMaps: null,
            editedVariant: null,
            meshyTaskId: null,
            errorMessage: null,
          },
          {
            schemeId: 'scheme_2',
            title: 'Queued',
            promptText: '',
            status: 'pending',
            texturedModelUrl: null,
            textureMaps: null,
            editedVariant: null,
            meshyTaskId: null,
            errorMessage: null,
          },
          {
            schemeId: 'scheme_3',
            title: 'Queued',
            promptText: '',
            status: 'pending',
            texturedModelUrl: null,
            textureMaps: null,
            editedVariant: null,
            meshyTaskId: null,
            errorMessage: null,
          },
        ]);
        const accepted = await startGenerateModelTextures(token, {
          sessionId,
          sourceText: payload.sourceText,
          documentFile: payload.documentFile,
          referenceImageFile: payload.referenceImageFile,
          selectedImageKeywords: payload.selectedImageKeywords,
        });
        return accepted.status === 'accepted';
      } catch (error) {
        setJoinError(parseApiError(error, 'Failed to generate model textures.'));
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
        setJoinError(parseApiError(error, 'Failed to analyze reference image.'));
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
        setJoinError(parseApiError(error, 'Failed to save selected image keywords.'));
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
      setJoinError(parseApiError(error, 'Failed to remove document.'));
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
      setJoinError(parseApiError(error, 'Failed to remove reference image.'));
      void syncTexturePlan();
    } finally {
      setTexturePlanSaving(false);
    }
  }, [sessionId, syncTexturePlan, token]);

  const handleSelectTexturedModel = useCallback((schemeId: string) => {
    if (!schemeId) {
      setSelectedTexturedSchemeId(null);
      return;
    }
    const model = texturedModels.find((m) => m.schemeId === schemeId);
    if (model?.texturedModelUrl) {
      setSelectedTexturedSchemeId(model.schemeId);
      setPreviewModeByScheme((current) => ({
        ...current,
        [model.schemeId]: model.editedVariant?.modelUrl ? current[model.schemeId] ?? 'edited' : 'meshy',
      }));
    }
  }, [texturedModels]);

  const handleAddTextureToCanvas = useCallback((schemeId: string) => {
    const model = texturedModels.find((item) => item.schemeId === schemeId);
    if (!model) {
      return;
    }
    const previewMode = previewModeByScheme[model.schemeId] === 'edited' && model.editedVariant?.baseColorUrl
      ? 'edited'
      : 'meshy';
    const baseColorTextureUrl =
      previewMode === 'edited' ? model.editedVariant?.baseColorUrl : model.textureMaps?.baseColor;
    if (!baseColorTextureUrl) {
      return;
    }
    const workspaceId = getTextureWorkspaceId(baseModel?.baseModelId ?? null, model);
    setSelectedTexturedSchemeId(model.schemeId);
    setActiveTextureWorkspaceId(workspaceId);
    const nextRequestId = ++canvasInsertRequestRef.current;
    setCanvasTextureLayer({
      requestId: nextRequestId,
      workspaceId,
      imageUrl: baseColorTextureUrl,
      label: model?.title ? `${model.title} texture layer` : 'meshy-base-color-texture-layer',
    });
  }, [baseModel?.baseModelId, previewModeByScheme, texturedModels]);

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
          `${selectedTexturedModel.schemeId}_edited_base_color.png`,
        );
        const nextState = await applyEditedTexture(token, {
          sessionId,
          schemeId: selectedTexturedModel.schemeId,
          editedBaseColorFile,
        });
        setTextureModelsStatus(nextState.status);
        setTexturedModels(nextState.models);
        setSelectedTexturedSchemeId(selectedTexturedModel.schemeId);
        setPreviewModeByScheme((current) => ({
          ...current,
          [selectedTexturedModel.schemeId]: 'edited',
        }));
      } catch (error) {
        setJoinError(parseApiError(error, 'Failed to apply edited texture to the locked model.'));
      } finally {
        setApplyTexturePending(false);
      }
    },
    [activeTextureWorkspaceId, selectedTexturedModel, sessionId, token],
  );

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
          <AppErrorBoundary title="Stage 1 rendering failed">
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
          <ParticipantSidebar />
        </div>
      );
    }

    if (uiStage === 2) {
      return (
        <div className="flex h-full min-h-0 overflow-hidden">
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
            <header className="relative z-20 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                {TOOL_OPTIONS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setTool(item.id)}
                    className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                      tool === item.id
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'bg-slate-50 text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    {item.icon}
                    {item.label}
                  </button>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600 transition-colors hover:bg-slate-100">
                  <Brush size={12} className="text-blue-500" />
                  <input
                    type="color"
                    title="Brush Color"
                    value={strokeColor}
                    onChange={(event) => setStrokeColor(event.target.value)}
                    className="h-6 w-6 cursor-pointer border-0 bg-transparent p-0"
                  />
                </label>
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600 transition-colors hover:bg-slate-100">
                  Fill
                  <input
                    type="color"
                    title="Fill Color"
                    value={fillColor}
                    onChange={(event) => setFillColor(event.target.value)}
                    className="h-6 w-6 cursor-pointer border-0 bg-transparent p-0"
                  />
                </label>
                <div className="hidden h-4 w-px bg-slate-200 sm:block" />
                <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                  <Save size={12} className={lastAutoSavedAt ? 'text-emerald-500' : ''} />
                  {lastAutoSavedAt ? `Autosaved ${lastAutoSavedAt}` : 'Waiting autosave'}
                </span>
              </div>
            </header>

            <div className="min-h-0 flex-1">
              <DesignerCanvas
                tool={tool}
                sessionId={sessionId}
                schemeId={activeTextureWorkspaceId}
                strokeColor={strokeColor}
                fillColor={fillColor}
                baseModelId={baseModel?.baseModelId ?? null}
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
              />
            </div>
          </section>
          <Stage2LinkedPreview
            baseModel={baseModel}
            linkedUvFocus={linkedUvFocus}
            onLinkedUvFocusChange={setLinkedUvFocus}
            texturedModels={texturedModels}
            textureModelsStatus={textureModelsStatus}
            selectedTexturedSchemeId={selectedTexturedSchemeId}
            selectedPreviewMode={selectedTexturePreviewMode}
            selectedTexturedModelUrl={selectedTexturedPreviewUrl}
            onSelectTexturedModel={handleSelectTexturedModel}
            onAddTextureToCanvas={handleAddTextureToCanvas}
            onPreviewModeChange={(mode) => {
              if (!selectedTexturedModel) {
                return;
              }
              setPreviewModeByScheme((current) => ({
                ...current,
                [selectedTexturedModel.schemeId]: mode,
              }));
            }}
          />
          <ParticipantSidebar />
        </div>
      );
    }

    if (uiStage === 3) {
      return (
        <div className="flex h-full min-h-0 overflow-hidden">
          <Stage3ReviewView
            schemes={reviewSchemes}
            baseModel={baseModel}
            isHost={isHost}
            currentUserId={currentUserId}
            onStarScheme={handleStarScheme}
            onRevertToDesign={isHost ? () => {
              void handleRevertStage();
            } : undefined}
            onAdvanceToPreview={isHost ? () => {
              void handleAdvanceStage();
            } : undefined}
            reverting={stageReverting}
            advancing={stageAdvancing}
          />
          <ParticipantSidebar />
        </div>
      );
    }

    return <Stage4PreviewView schemes={reviewSchemes} baseModel={baseModel} />;
  };

  if (screen === 'entry') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-100 via-blue-50 to-slate-200 p-4">
        <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-6 shadow-lg">
          <h1 className="text-xl font-semibold text-slate-800">Co-Track Meeting Join</h1>
          <p className="mt-2 text-sm text-slate-500">Input your name and invite code, then complete device check.</p>

          <div className="mt-5 space-y-3">
            <label className="block text-sm text-slate-700">
              Name
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="e.g. Alice"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </label>

            <label className="block text-sm text-slate-700">
              Invite Code
              <input
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value.trim())}
                placeholder="Demo invite code 555555"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:bg-white"
              />
            </label>

            <label className="block text-sm text-slate-700">
              Role
              <select
                value={selectedRole}
                onChange={(event) => setSelectedRole(event.target.value as MeetingRole)}
                className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:bg-white"
              >
                <option value="host">Host</option>
                <option value="designer">Designer</option>
                <option value="observer">Observer</option>
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
            className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
          >
            <LogIn size={15} />
            Next: Device Check
            <ArrowRight size={15} />
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
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-800">{sessionName || 'Unnamed Session'}</p>
            <p className="text-xs text-slate-500">
              Invite {inviteCode} | Role {meetingRole} | Backend stage {backendStage}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {STAGE_ORDER.map((stage) => (
              <span
                key={stage}
                className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  stage <= uiStage ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'
                }`}
              >
                {STAGE_LABELS[stage]}
              </span>
            ))}
          </div>

          {isHost && uiStage < 3 ? (
            <button
              type="button"
              onClick={() => {
                void handleAdvanceStage();
              }}
              disabled={stageAdvancing}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              <span
                aria-hidden
                className={`h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-200 border-t-transparent ${
                  stageAdvancing ? '' : 'hidden'
                }`}
              />
              <ArrowRight size={13} className={stageAdvancing ? 'hidden' : ''} />
              Advance Stage
            </button>
          ) : null}
        </div>

        {joinError ? (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            <AlertCircle size={14} className="mt-0.5" />
            <span>{joinError}</span>
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1">{renderMeetingStage()}</div>

      <MeetingDock
        role={meetingRole}
        localUserName={displayName}
        localStream={rtc.localStream}
        audioEnabled={rtc.audioEnabled}
        videoEnabled={rtc.videoEnabled}
        canPublishMedia={rtc.canPublishMedia}
        handRaised={rtc.handRaised}
        peers={rtc.peers}
        connecting={rtc.connecting}
        joined={rtc.joined}
        error={rtc.error}
        onToggleAudio={rtc.toggleAudio}
        onToggleVideo={rtc.toggleVideo}
        onLeave={handleLeaveMeeting}
        onRequestSpeak={rtc.requestSpeak}
        onApproveSpeak={rtc.approveSpeak}
      />
    </div>
  );
};

export default App;
