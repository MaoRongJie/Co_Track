import axios from 'axios';
import type {
  BaseModelMeta,
  BaseModelSource,
  BriefKeywordSnapshot,
  DesignBrief,
  ProductCategory,
  ProductProfile,
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
  MeetingRole,
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
): Promise<{ token: string; user: AuthUser }> => {
  const local = normalizeEmailName(displayName);
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
  const response = await api.post<JoinSessionResponse>(
    '/api/sessions/join',
    { invite_code: inviteCode, role },
    authHeader(token),
  );
  return response.data;
};

export const fetchSessionDetail = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.get<JoinedSession>(`/api/sessions/${sessionId}`, authHeader(token));
  return response.data;
};

export const advanceSessionStage = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.post<JoinedSession>(`/api/sessions/${sessionId}/advance`, {}, authHeader(token));
  return response.data;
};

export const revertSessionStage = async (token: string, sessionId: number): Promise<JoinedSession> => {
  const response = await api.post<JoinedSession>(`/api/sessions/${sessionId}/revert`, {}, authHeader(token));
  return response.data;
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

type BackendAiMessage = {
  id: number;
  session_id: number;
  user_id: number | null;
  role: 'user' | 'assistant' | 'system';
  mode: AiChatMode | null;
  content: string;
  created_at: string;
};

type BackendGeneratedImage = {
  id: number;
  session_id: number;
  prompt: string;
  style_hint: string | null;
  revised_prompt: string | null;
  image_url: string;
  created_at: string;
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

const mapBackendAiMessage = (message: BackendAiMessage): AiChatMessage => ({
  id: message.id,
  sessionId: message.session_id,
  userId: message.user_id,
  role: message.role,
  mode: message.mode,
  content: message.content,
  createdAt: message.created_at,
});

const mapBackendGeneratedImage = (item: BackendGeneratedImage): GeneratedPatternImage => ({
  id: item.id,
  sessionId: item.session_id,
  prompt: item.prompt,
  styleHint: item.style_hint,
  revisedPrompt: item.revised_prompt,
  imageUrl: item.image_url,
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

export type AiChatMode = 'creative' | 'image';

export type AiChatMessage = {
  id: number;
  sessionId: number;
  userId: number | null;
  role: 'user' | 'assistant' | 'system';
  mode: AiChatMode | null;
  content: string;
  createdAt: string;
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
  meshy_task_id: string | null;
  error_message: string | null;
};

type BackendTextureModelsState = {
  session_id: number;
  status: TextureModelsState['status'];
  models: BackendTexturedModel[];
  updated_at: string;
};

const mapBackendTexturedModel = (item: BackendTexturedModel): TexturedModel => ({
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
  meshyTaskId: item.meshy_task_id,
  errorMessage: item.error_message,
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
    schemeId: string;
    editedBaseColorFile: File;
  },
): Promise<TextureModelsState> => {
  const formData = new FormData();
  formData.append('session_id', String(payload.sessionId));
  formData.append('scheme_id', payload.schemeId);
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

const parseSseChunk = (
  rawEvent: string,
): {
  event: string;
  data: string;
} | null => {
  const lines = rawEvent.replace(/\r/g, '').split('\n');
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  return {
    event,
    data: dataLines.join('\n'),
  };
};

const findSseBoundary = (buffer: string): { index: number; length: number } | null => {
  const lf = buffer.indexOf('\n\n');
  const crlf = buffer.indexOf('\r\n\r\n');

  if (lf < 0 && crlf < 0) {
    return null;
  }
  if (lf >= 0 && (crlf < 0 || lf < crlf)) {
    return { index: lf, length: 2 };
  }
  return { index: crlf, length: 4 };
};

const parseFailedFetchResponse = async (response: Response): Promise<string> => {
  try {
    const json = (await response.json()) as { detail?: string };
    if (typeof json.detail === 'string' && json.detail.trim().length > 0) {
      return json.detail;
    }
  } catch {
    // ignore json parse error and fallback to status text
  }
  return `Request failed with status ${response.status}`;
};

export const streamAiChat = async (
  token: string,
  payload: {
    sessionId: number;
    message: string;
    mode?: AiChatMode;
  },
  handlers?: {
    onChunk?: (delta: string, fullText: string) => void;
    onDone?: (assistant: AiChatMessage) => void;
    onError?: (message: string) => void;
  },
): Promise<{ assistantMessage: AiChatMessage | null; fullText: string }> => {
  const response = await fetch(toAbsoluteApiUrl('/api/ai/chat'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: payload.sessionId,
      message: payload.message,
      mode: payload.mode ?? 'creative',
      stream: true,
    }),
  });

  if (!response.ok) {
    throw new Error(await parseFailedFetchResponse(response));
  }
  if (!response.body) {
    throw new Error('AI stream is not available from server.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';
  let assistantMessage: AiChatMessage | null = null;
  let doneNotified = false;

  const consumeRawEvent = (rawEvent: string): void => {
    const parsedEvent = parseSseChunk(rawEvent);
    if (!parsedEvent) {
      return;
    }

    const parsedData = JSON.parse(parsedEvent.data) as Record<string, unknown>;
    const eventName = parsedEvent.event.trim().toLowerCase();

    const isChunkEvent =
      eventName === 'chunk' ||
      (eventName === 'message' && typeof parsedData.delta === 'string' && parsedData.delta.length > 0);
    if (isChunkEvent) {
      const delta = typeof parsedData.delta === 'string' ? parsedData.delta : '';
      if (delta) {
        fullText += delta;
        handlers?.onChunk?.(delta, fullText);
      }
      return;
    }

    const backendAssistant =
      parsedData.assistant_message && typeof parsedData.assistant_message === 'object'
        ? (parsedData.assistant_message as BackendAiMessage)
        : undefined;
    const isDoneEvent = eventName === 'done' || Boolean(backendAssistant);
    if (isDoneEvent) {
      if (backendAssistant) {
        assistantMessage = mapBackendAiMessage(backendAssistant);
        handlers?.onDone?.(assistantMessage);
        doneNotified = true;
      } else if (fullText.trim().length > 0 && !doneNotified) {
        assistantMessage = {
          id: -Date.now(),
          sessionId: payload.sessionId,
          userId: null,
          role: 'assistant',
          mode: payload.mode ?? 'creative',
          content: fullText,
          createdAt: new Date().toISOString(),
        };
        handlers?.onDone?.(assistantMessage);
        doneNotified = true;
      }
      return;
    }

    const isErrorEvent =
      eventName === 'error' ||
      (eventName === 'message' &&
        typeof parsedData.message === 'string' &&
        parsedData.message.trim().length > 0 &&
        typeof parsedData.code === 'string');
    if (isErrorEvent) {
      const message =
        typeof parsedData.message === 'string' && parsedData.message.trim().length > 0
          ? parsedData.message
          : 'AI stream failed.';
      handlers?.onError?.(message);
      throw new Error(message);
    }
  };

  const drainSseBuffer = (allowTrailingEvent: boolean): void => {
    let boundary = findSseBoundary(buffer);
    while (boundary) {
      const rawEvent = buffer.slice(0, boundary.index);
      buffer = buffer.slice(boundary.index + boundary.length);
      if (rawEvent.trim().length > 0) {
        consumeRawEvent(rawEvent);
      }
      boundary = findSseBoundary(buffer);
    }

    if (allowTrailingEvent && buffer.trim().length > 0) {
      consumeRawEvent(buffer);
      buffer = '';
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    drainSseBuffer(false);
  }

  buffer += decoder.decode();
  drainSseBuffer(true);

  if (!doneNotified && fullText.trim().length > 0) {
    assistantMessage = {
      id: -Date.now(),
      sessionId: payload.sessionId,
      userId: null,
      role: 'assistant',
      mode: payload.mode ?? 'creative',
      content: fullText,
      createdAt: new Date().toISOString(),
    };
    handlers?.onDone?.(assistantMessage);
    doneNotified = true;
  }

  return { assistantMessage, fullText };
};

export const fetchAiChatHistory = async (
  token: string,
  payload: { sessionId: number; limit?: number; beforeId?: number },
): Promise<{ items: AiChatMessage[]; hasMore: boolean }> => {
  const response = await api.get<{ items: BackendAiMessage[]; has_more: boolean }>('/api/ai/chat/history', {
    ...authHeader(token),
    params: {
      session_id: payload.sessionId,
      limit: payload.limit ?? 30,
      before_id: payload.beforeId,
    },
  });

  return {
    items: response.data.items.map(mapBackendAiMessage),
    hasMore: response.data.has_more,
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
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detail;
    }
    if (!error.response) {
      const reason = error.code === 'ECONNABORTED' ? '请求超时' : '无法连接到后端服务';
      return `${reason}（${API_BASE_URL}）`;
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
