import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import {
  AlertCircle,
  Box,
  Check,
  HardHat,
  ImageIcon,
  Link2,
  LoaderCircle,
  Maximize2,
  MessageCircle,
  MessageSquare,
  Paintbrush,
  Sparkles,
  Plus,
  Share2,
  Users,
  X,
} from 'lucide-react';
import {
  BufferAttribute,
  BufferGeometry,
  DoubleSide,
  Matrix4,
  Mesh,
  Object3D,
  Vector2,
  Vector3,
} from 'three';
import AppErrorBoundary from './AppErrorBoundary.tsx';
import {
  fetchSceneRenderMedia,
  generateSceneRenderImage,
  parseApiError,
  type Stage4MediaAsset,
} from '../services/apiClient.ts';
import type { BaseModelMeta, TexturedModel, UvFocusPoint } from '../types/design.ts';

type Stage2ReviewRole = 'engineering' | 'passenger';

type Stage2ReviewCommentState = {
  label: string;
  shortcutKey: string;
  open: boolean;
  comment: string | null;
  loading: boolean;
  error: string | null;
};

interface Stage2LinkedPreviewProps {
  baseModel: BaseModelMeta | null;
  token?: string | null;
  sessionId?: number | null;
  canUploadCustomResult?: boolean;
  linkedUvFocus: UvFocusPoint | null;
  onLinkedUvFocusChange: (point: UvFocusPoint | null) => void;
  texturedModels?: TexturedModel[];
  textureModelsStatus?: 'idle' | 'queued' | 'processing' | 'completed' | 'failed';
  selectedTexturedResultId?: string | null;
  selectedPreviewMode?: 'meshy' | 'edited';
  selectedTexturedModelUrl?: string | null;
  onSelectTexturedModel?: (resultId: string) => void;
  onAddTextureToCanvas?: (resultId: string) => void;
  deletingResultId?: string | null;
  onDeleteTexturedModel?: (resultId: string) => Promise<boolean> | boolean;
  onUploadCustomTexturedModel?: (payload: {
    title: string;
    modelFile: File;
    baseColorFile: File;
  }) => Promise<boolean> | boolean;
  ownSharedResultIds?: string[];
  sharingResultsPending?: boolean;
  onShareResults?: (resultIds: string[]) => Promise<boolean> | boolean;
  sharedResultsViewer?: {
    open: boolean;
    sourceUserName: string;
    models: TexturedModel[];
    highlightedResultId: string | null;
    selectedResultIds: string[];
    loading: boolean;
    importing: boolean;
  };
  onCloseSharedResultsViewer?: () => void;
  onHighlightSharedResult?: (resultId: string) => void;
  onToggleSharedResultSelection?: (resultId: string) => void;
  onImportSharedResults?: () => void;
  onPreviewModeChange?: (mode: 'meshy' | 'edited') => void;
  reviewCommentStates?: Record<Stage2ReviewRole, Stage2ReviewCommentState>;
  onCloseReviewComment?: (role: Stage2ReviewRole) => void;
}

type TexturedResultGroup = {
  key: string;
  label: string;
  items: TexturedModel[];
};

type TriangleSelection = {
  meshName: string;
  uv: { u: number; v: number };
  worldVertices: [Vector3, Vector3, Vector3];
};

const uvToLabel = (point: { u: number; v: number } | null): string => {
  if (!point) {
    return '-';
  }
  return `${point.u.toFixed(3)}, ${point.v.toFixed(3)}`;
};

const DEFAULT_SHARED_SCENE_PROMPT =
  '在现代高铁站台或运行线路场景中展示这辆高铁，真实摄影风格，保持车身涂装和结构细节。';

const LinkedModelScene: React.FC<{
  modelUrl: string;
  linkedUvFocus: UvFocusPoint | null;
  onLinkedUvFocusChange: (point: UvFocusPoint | null) => void;
  onSelectionChange: (selection: TriangleSelection | null) => void;
}> = ({ modelUrl, linkedUvFocus, onLinkedUvFocusChange, onSelectionChange }) => {
  const { scene } = useGLTF(modelUrl);
  const sceneClone = useMemo(() => scene.clone(true), [scene]);
  const [clickedSelection, setClickedSelection] = useState<TriangleSelection | null>(null);

  useEffect(() => {
    sceneClone.updateWorldMatrix(true, true);
  }, [sceneClone]);

  const uvSelection = useMemo(() => {
    if (!linkedUvFocus || linkedUvFocus.source !== 'uv') {
      return null;
    }
    sceneClone.updateWorldMatrix(true, true);
    return findTriangleByUv(sceneClone, linkedUvFocus.u, linkedUvFocus.v);
  }, [linkedUvFocus, sceneClone]);

  const selection = linkedUvFocus?.source === 'uv' ? uvSelection : clickedSelection;

  useEffect(() => {
    onSelectionChange(selection);
  }, [onSelectionChange, selection]);

  const overlayGeometry = useMemo(() => {
    if (!selection) {
      return null;
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new BufferAttribute(
        new Float32Array([
          selection.worldVertices[0].x,
          selection.worldVertices[0].y,
          selection.worldVertices[0].z,
          selection.worldVertices[1].x,
          selection.worldVertices[1].y,
          selection.worldVertices[1].z,
          selection.worldVertices[2].x,
          selection.worldVertices[2].y,
          selection.worldVertices[2].z,
        ]),
        3,
      ),
    );
    geometry.setIndex([0, 1, 2]);
    geometry.computeVertexNormals();
    return geometry;
  }, [selection]);

  const overlayEdges = useMemo(() => {
    if (!selection) {
      return null;
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new BufferAttribute(
        new Float32Array([
          selection.worldVertices[0].x,
          selection.worldVertices[0].y,
          selection.worldVertices[0].z,
          selection.worldVertices[1].x,
          selection.worldVertices[1].y,
          selection.worldVertices[1].z,
          selection.worldVertices[1].x,
          selection.worldVertices[1].y,
          selection.worldVertices[1].z,
          selection.worldVertices[2].x,
          selection.worldVertices[2].y,
          selection.worldVertices[2].z,
          selection.worldVertices[2].x,
          selection.worldVertices[2].y,
          selection.worldVertices[2].z,
          selection.worldVertices[0].x,
          selection.worldVertices[0].y,
          selection.worldVertices[0].z,
        ]),
        3,
      ),
    );
    return geometry;
  }, [selection]);

  useEffect(() => {
    return () => {
      overlayGeometry?.dispose();
      overlayEdges?.dispose();
    };
  }, [overlayEdges, overlayGeometry]);

  const handleMeshClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    const mesh = event.object as Mesh;
    const faceIndex = event.faceIndex ?? null;
    const uv = event.uv ?? null;
    if (!(mesh instanceof Mesh) || faceIndex === null || !uv) {
      return;
    }

    const nextSelection = buildTriangleSelection(mesh, faceIndex, { u: uv.x, v: uv.y });
    if (!nextSelection) {
      return;
    }
    setClickedSelection(nextSelection);
    onSelectionChange(nextSelection);
    onLinkedUvFocusChange({
      u: uv.x,
      v: uv.y,
      source: 'model',
      token: Date.now(),
    });
  };

  return (
    <>
      <Bounds fit clip observe margin={1.15}>
        <primitive object={sceneClone} onClick={handleMeshClick} />
      </Bounds>
      {overlayGeometry ? (
        <mesh geometry={overlayGeometry} renderOrder={50}>
          <meshBasicMaterial
            color="#f97316"
            transparent
            opacity={0.42}
            side={DoubleSide}
            depthWrite={false}
            polygonOffset
            polygonOffsetFactor={-2}
          />
        </mesh>
      ) : null}
      {overlayEdges ? (
        <lineSegments geometry={overlayEdges} renderOrder={51}>
          <lineBasicMaterial color="#ea580c" />
        </lineSegments>
      ) : null}
    </>
  );
};

const Stage2LinkedPreview: React.FC<Stage2LinkedPreviewProps> = ({
  baseModel,
  token = null,
  sessionId = null,
  canUploadCustomResult = false,
  linkedUvFocus,
  onLinkedUvFocusChange,
  texturedModels = [],
  textureModelsStatus = 'idle',
  selectedTexturedResultId,
  selectedPreviewMode = 'meshy',
  selectedTexturedModelUrl,
  onSelectTexturedModel,
  onAddTextureToCanvas,
  deletingResultId = null,
  onDeleteTexturedModel,
  onUploadCustomTexturedModel,
  ownSharedResultIds = [],
  sharingResultsPending = false,
  onShareResults,
  sharedResultsViewer,
  onCloseSharedResultsViewer,
  onHighlightSharedResult,
  onToggleSharedResultSelection,
  onImportSharedResults,
  onPreviewModeChange,
  reviewCommentStates,
  onCloseReviewComment,
}) => {
  const [selection, setSelection] = useState<TriangleSelection | null>(null);
  const [uploadPanelOpen, setUploadPanelOpen] = useState(false);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadModelFile, setUploadModelFile] = useState<File | null>(null);
  const [uploadBaseColorFile, setUploadBaseColorFile] = useState<File | null>(null);
  const [uploadingCustomResult, setUploadingCustomResult] = useState(false);
  const [shareSelectionMode, setShareSelectionMode] = useState(false);
  const [selectedShareResultIds, setSelectedShareResultIds] = useState<string[]>(ownSharedResultIds);
  const sharedPreviewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [sharedScenePrompt, setSharedScenePrompt] = useState(DEFAULT_SHARED_SCENE_PROMPT);
  const [sharedRenderMediaItems, setSharedRenderMediaItems] = useState<Stage4MediaAsset[]>([]);
  const [sharedRenderLoading, setSharedRenderLoading] = useState(false);
  const [sharedRenderGenerating, setSharedRenderGenerating] = useState(false);
  const [sharedRenderError, setSharedRenderError] = useState<string | null>(null);
  const [sharedRenderLightboxItem, setSharedRenderLightboxItem] = useState<Stage4MediaAsset | null>(null);
  const [sharedCommentingResultId, setSharedCommentingResultId] = useState<string | null>(null);

  const previewModelUrl = selectedTexturedModelUrl || baseModel?.modelUrl || null;
  const hasTexturedModels = texturedModels.length > 0;
  const selectedTexturedModel =
    selectedTexturedResultId
      ? texturedModels.find((model) => model.resultId === selectedTexturedResultId) ?? null
      : null;
  const canAddPreviewTextureToCanvas = Boolean(
    selectedTexturedModel?.textureMaps?.baseColor || selectedTexturedModel?.editedVariant?.baseColorUrl,
  );
  const previewUsesRemoteMeshyAsset = Boolean(
    previewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(previewModelUrl),
  );
  const completedShareCandidates = useMemo(
    () => texturedModels.filter((model) => model.status === 'completed'),
    [texturedModels],
  );
  const sharedPreviewModel =
    sharedResultsViewer?.highlightedResultId
      ? sharedResultsViewer.models.find((model) => model.resultId === sharedResultsViewer.highlightedResultId) ?? null
      : sharedResultsViewer?.models[0] ?? null;
  const sharedPreviewModelUrl =
    sharedPreviewModel?.editedVariant?.modelUrl ?? sharedPreviewModel?.texturedModelUrl ?? null;
  const sharedPreviewUsesRemoteMeshyAsset = Boolean(
    sharedPreviewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(sharedPreviewModelUrl),
  );
  const sharedRenderImages = useMemo(
    () => sharedRenderMediaItems.filter((item) => item.mediaType === 'image'),
    [sharedRenderMediaItems],
  );
  const canGenerateSharedSceneImage = Boolean(
    token &&
    sessionId &&
    sharedPreviewModel &&
    sharedPreviewModelUrl &&
    !sharedPreviewUsesRemoteMeshyAsset &&
    sharedScenePrompt.trim(),
  );

  const loadSharedRenderMedia = useCallback(async (resultId: string | null | undefined) => {
    if (!token || !sessionId || !resultId) {
      setSharedRenderMediaItems([]);
      return;
    }
    setSharedRenderLoading(true);
    setSharedRenderError(null);
    try {
      const items = await fetchSceneRenderMedia(token, { sessionId, resultId });
      setSharedRenderMediaItems(items.filter((item) => item.mediaType === 'image'));
    } catch (error) {
      setSharedRenderMediaItems([]);
      setSharedRenderError(parseApiError(error, '加载共享方案渲染图失败。'));
    } finally {
      setSharedRenderLoading(false);
    }
  }, [sessionId, token]);

  useEffect(() => {
    setSelectedShareResultIds(ownSharedResultIds);
  }, [ownSharedResultIds]);

  useEffect(() => {
    sharedPreviewCanvasRef.current = null;
    setSharedRenderLightboxItem(null);
    if (!sharedResultsViewer?.open || !sharedPreviewModel?.resultId) {
      setSharedRenderMediaItems([]);
      setSharedRenderError(null);
      return;
    }
    void loadSharedRenderMedia(sharedPreviewModel.resultId);
  }, [loadSharedRenderMedia, sharedPreviewModel?.resultId, sharedResultsViewer?.open]);
  const texturedResultGroups = useMemo<TexturedResultGroup[]>(() => {
    const groups: TexturedResultGroup[] = [];
    const groupIndexByKey = new Map<string, number>();
    const generatedBatchOrder = new Map<string, number>();
    let generatedBatchCount = 0;

    for (const model of texturedModels) {
      let groupKey = 'legacy';
      let label = '历史方案';

      if (model.sourceType === 'imported') {
        groupKey = 'imported';
        label = '共享导入';
      } else if (model.sourceType === 'uploaded') {
        groupKey = 'uploaded';
        label = '手动上传';
      } else if (model.batchId && model.batchId !== 'legacy') {
        if (!generatedBatchOrder.has(model.batchId)) {
          generatedBatchCount += 1;
          generatedBatchOrder.set(model.batchId, generatedBatchCount);
        }
        groupKey = `generated:${model.batchId}`;
        label = `生成批次 ${generatedBatchOrder.get(model.batchId)}`;
      }

      const existingIndex = groupIndexByKey.get(groupKey);
      if (existingIndex == null) {
        groupIndexByKey.set(groupKey, groups.length);
        groups.push({ key: groupKey, label, items: [model] });
        continue;
      }
      groups[existingIndex].items.push(model);
    }

    return groups;
  }, [texturedModels]);

  const handleUploadCustomResult = async () => {
    if (!onUploadCustomTexturedModel || !uploadModelFile || !uploadBaseColorFile) {
      return;
    }
    try {
      setUploadingCustomResult(true);
      const succeeded = await onUploadCustomTexturedModel({
        title: uploadTitle,
        modelFile: uploadModelFile,
        baseColorFile: uploadBaseColorFile,
      });
      if (succeeded === false) {
        return;
      }
      setUploadPanelOpen(false);
      setUploadTitle('');
      setUploadModelFile(null);
      setUploadBaseColorFile(null);
    } finally {
      setUploadingCustomResult(false);
    }
  };

  const handleToggleShareResult = (resultId: string) => {
    setSelectedShareResultIds((current) =>
      current.includes(resultId) ? current.filter((item) => item !== resultId) : [...current, resultId],
    );
  };

  const handlePublishSharedResults = async () => {
    if (!onShareResults) {
      return;
    }
    const succeeded = await onShareResults(selectedShareResultIds);
    if (succeeded === false) {
      return;
    }
    setShareSelectionMode(false);
  };

  const handleGenerateSharedSceneImage = useCallback(async () => {
    if (!token || !sessionId || !sharedPreviewModel) {
      setSharedRenderError('共享方案渲染图生成尚未准备好。');
      return;
    }
    if (!sharedScenePrompt.trim()) {
      setSharedRenderError('请先填写场景描述。');
      return;
    }
    if (sharedPreviewUsesRemoteMeshyAsset || !sharedPreviewCanvasRef.current) {
      setSharedRenderError('当前共享 3D 预览无法截图。');
      return;
    }

    setSharedRenderGenerating(true);
    setSharedRenderError(null);
    try {
      const screenshotDataUrl = sharedPreviewCanvasRef.current.toDataURL('image/jpeg', 0.92);
      const result = await generateSceneRenderImage(token, {
        sessionId,
        resultId: sharedPreviewModel.resultId,
        schemeName: sharedPreviewModel.title || sharedPreviewModel.resultId,
        screenshotDataUrl,
        imagePrompt: sharedScenePrompt.trim(),
      });
      if (result.mediaAsset && result.mediaAsset.mediaType === 'image') {
        setSharedRenderMediaItems((current) => [
          result.mediaAsset!,
          ...current.filter((item) => item.id !== result.mediaAsset!.id),
        ]);
      } else {
        await loadSharedRenderMedia(sharedPreviewModel.resultId);
      }
    } catch (error) {
      setSharedRenderError(parseApiError(error, '生成共享方案渲染图失败。'));
    } finally {
      setSharedRenderGenerating(false);
    }
  }, [
    loadSharedRenderMedia,
    sessionId,
    sharedPreviewModel,
    sharedPreviewUsesRemoteMeshyAsset,
    sharedScenePrompt,
    token,
  ]);

  const handleDeleteResult = async (model: TexturedModel) => {
    if (!onDeleteTexturedModel) {
      return;
    }
    const label = model.title || model.resultId;
    const confirmed = window.confirm(
      `确定从工作区删除“${label}”吗？如果该方案已共享，也会从公共评审中移除。`,
    );
    if (!confirmed) {
      return;
    }
    await onDeleteTexturedModel(model.resultId);
  };

  if (!baseModel?.modelUrl) {
    return (
      <aside className="z-20 flex w-[22rem] shrink-0 flex-col border-l border-slate-200 bg-white p-4">
        <div className="flex h-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 text-center">
          <div className="rounded-2xl bg-slate-100 p-4 text-slate-500">
            <Box size={26} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-700">暂无 3D 预览</p>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="z-20 flex w-[22rem] shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="flex-1 overflow-y-auto p-4">
        {/* Header */}
        <div className="mb-4 flex flex-col gap-1">
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">S2</p>
          <div className="flex items-center gap-2">
            <Link2 size={14} className="text-slate-400" />
            <h3 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
              {selectedTexturedModel ? '评估' : '预览'}
            </h3>
          </div>
        </div>

        {/* 3D Preview */}
        <div className="relative h-72 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-sm">
          {selectedTexturedModel ? (
            <div className="absolute right-2 top-2 z-20">
              <button
                type="button"
                onClick={() => canAddPreviewTextureToCanvas && onAddTextureToCanvas?.(selectedTexturedModel.resultId)}
                disabled={!canAddPreviewTextureToCanvas}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold shadow-sm transition ${
                  canAddPreviewTextureToCanvas
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'cursor-not-allowed bg-slate-100 text-slate-400 hover:bg-slate-100'
                }`}
              >
                <Plus size={12} />
                添加
              </button>
            </div>
          ) : null}
          {selectedTexturedModel?.editedVariant?.modelUrl ? (
            <div className="absolute left-2 top-2 z-20 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white/95 p-1 text-[11px] text-slate-700 shadow-sm">
              <button
                type="button"
                onClick={() => onPreviewModeChange?.('meshy')}
                className={`rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider transition ${
                  selectedPreviewMode === 'meshy'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                Meshy
              </button>
              <button
                type="button"
                onClick={() => onPreviewModeChange?.('edited')}
                className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider transition ${
                  selectedPreviewMode === 'edited'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                <Paintbrush size={10} />
                已编辑
              </button>
            </div>
          ) : null}

          {previewUsesRemoteMeshyAsset ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center">
              <div className="rounded-2xl bg-amber-50 p-4 text-amber-500">
                <AlertCircle size={24} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">远程预览不可用</p>
              </div>
            </div>
          ) : (
            <AppErrorBoundary key={previewModelUrl ?? 'empty'} title="3D 预览失败">
              <Suspense
                fallback={
            <div className="flex h-full items-center justify-center gap-2 text-[11px] font-medium text-slate-400">
              <LoaderCircle size={14} className="animate-spin" />
              加载中...
            </div>
                }
              >
                <Canvas camera={{ position: [4.5, 2.8, 5.8], fov: 42 }}>
                  <color attach="background" args={['#f8fafc']} />
                  <ambientLight intensity={0.9} />
                  <directionalLight intensity={1.15} position={[4, 7, 5]} />
                  <directionalLight intensity={0.45} position={[-3, 4, -4]} />
                  <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.2, 0]} receiveShadow>
                    <planeGeometry args={[20, 20]} />
                    <meshStandardMaterial color="#e2e8f0" />
                  </mesh>
                  <LinkedModelScene
                    key={previewModelUrl!}
                    modelUrl={previewModelUrl!}
                    linkedUvFocus={selectedTexturedModel ? null : linkedUvFocus}
                    onLinkedUvFocusChange={onLinkedUvFocusChange}
                    onSelectionChange={setSelection}
                  />
                  <OrbitControls makeDefault enablePan enableRotate enableZoom />
                </Canvas>
              </Suspense>
            </AppErrorBoundary>
          )}
        </div>

        {/* UV Info (collapsed when showing textured models) */}
        {!selectedTexturedModel ? (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
            <div className="flex items-center justify-between">
              <span>
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">网格</span>:{' '}
                <span className="font-semibold text-slate-800">{selection?.meshName ?? '-'}</span>
              </span>
              <span>
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">UV</span>:{' '}
                <span className="font-semibold text-slate-800">{uvToLabel(linkedUvFocus ? { u: linkedUvFocus.u, v: linkedUvFocus.v } : null)}</span>
              </span>
            </div>
          </div>
        ) : null}

        {/* Textured Model Cards */}
        <div className="mt-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Paintbrush size={14} className="text-blue-600" />
              <h4 className="text-xs font-semibold text-slate-700">方案</h4>
            </div>
            <div className="flex items-center gap-2">
              {hasTexturedModels && selectedTexturedModel ? (
                <button
                  type="button"
                  onClick={() => onSelectTexturedModel?.('')}
                  className="text-[10px] font-bold uppercase tracking-wider text-slate-400 hover:text-blue-600 transition"
                  onClickCapture={(e) => {
                    e.stopPropagation();
                  }}
                >
                  重置
                </button>
              ) : null}
            </div>
          </div>

          {selectedTexturedModel?.status === 'completed' && reviewCommentStates ? (
            <div className="mb-3 rounded-2xl border border-amber-100 bg-amber-50/70 px-3 py-2.5 text-[11px] leading-5 text-slate-600">
              <span className="font-semibold text-slate-700">快速评审：</span>{' '}
              <span className="rounded bg-white px-1.5 py-0.5 font-bold text-amber-700">F</span> /{' '}
              <span className="rounded bg-white px-1.5 py-0.5 font-bold text-amber-700">G</span>
            </div>
          ) : null}

          {hasTexturedModels ? (
            <div className="space-y-3">
              {texturedResultGroups.map((group, groupIndex) => (
                <div key={group.key} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{group.label}</p>
                  </div>
                  <div className={`grid gap-2 ${canUploadCustomResult && onUploadCustomTexturedModel && groupIndex === texturedResultGroups.length - 1 ? 'grid-cols-4' : 'grid-cols-3'}`}>
                    {group.items.map((model) => {
                      const isSelected = model.resultId === selectedTexturedResultId;
                      const isCompleted = model.status === 'completed';
                      const isFailed = model.status === 'failed';
                      const openReviewRoles = isSelected && reviewCommentStates
                        ? (Object.entries(reviewCommentStates) as [Stage2ReviewRole, Stage2ReviewCommentState][])
                            .filter(([, state]) => state.open)
                            .map(([role]) => role)
                        : [];
                      const canDeleteModel =
                        Boolean(onDeleteTexturedModel) && model.status !== 'processing' && model.status !== 'pending';
                      const deletePending = deletingResultId === model.resultId;

                      return (
                        <div
                          key={model.resultId}
                          className={`relative flex flex-col items-center gap-1.5 rounded-xl border p-3 text-center transition-all duration-300 ${
                            isSelected
                              ? 'border-blue-400 bg-blue-50 shadow-sm ring-2 ring-blue-500/20'
                              : isCompleted
                                ? 'border-slate-200 bg-white shadow-sm'
                                : isFailed
                                  ? 'border-red-200 bg-red-50/50'
                              : 'border-slate-200 bg-slate-50'
                          }`}
                        >
                          {(isSelected || canDeleteModel) ? (
                            <div className="absolute right-1.5 top-1.5 flex items-center gap-1">
                              {isSelected ? (
                                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-600 text-white shadow-sm">
                                  <Check size={10} />
                                </div>
                              ) : null}
                              {canDeleteModel ? (
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void handleDeleteResult(model);
                                  }}
                                  disabled={deletePending}
                                  className={`inline-flex h-5 w-5 items-center justify-center rounded-full border transition ${
                                    deletePending
                                      ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                                      : 'border-slate-200 bg-white text-slate-400 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600'
                                  }`}
                                  title="删除该纹理方案"
                                  aria-label={`删除 ${model.title || model.resultId}`}
                                >
                                  {deletePending ? <LoaderCircle size={10} className="animate-spin" /> : <X size={10} />}
                                </button>
                              ) : null}
                            </div>
                          ) : null}

                          <button
                            type="button"
                            onClick={() => isCompleted && onSelectTexturedModel?.(model.resultId)}
                            disabled={!isCompleted}
                            className={`flex w-full flex-col items-center gap-1.5 rounded-lg transition ${
                              isCompleted ? 'cursor-pointer' : 'cursor-default'
                            }`}
                          >
                            <div className={`rounded-lg p-2 ${
                              isSelected ? 'bg-blue-100 text-blue-700' :
                              isCompleted ? 'bg-slate-100 text-slate-600' :
                              isFailed ? 'bg-red-100 text-red-500' :
                              'bg-slate-100 text-slate-400'
                            }`}>
                              {model.status === 'processing' || model.status === 'pending' ? (
                                <LoaderCircle size={16} className="animate-spin" />
                              ) : (
                                <Box size={16} />
                              )}
                            </div>

                            <span className={`text-[10px] font-bold leading-tight uppercase tracking-tight ${
                              isSelected ? 'text-blue-700' :
                              isFailed ? 'text-red-600' :
                              'text-slate-600'
                            }`}>
                              {model.title || model.resultId}
                            </span>
                            <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest ${
                              model.sourceType === 'uploaded'
                                ? 'bg-emerald-50 text-emerald-600'
                                : model.sourceType === 'imported'
                                  ? 'bg-violet-50 text-violet-600'
                                  : 'bg-slate-100 text-slate-500'
                            }`}>
                              {model.sourceType === 'uploaded'
                                ? '已上传'
                                : model.sourceType === 'imported'
                                  ? '共享'
                                  : model.schemeId}
                            </span>
                            {model.sourceType === 'imported' && model.sharedOrigin ? (
                              <span className="text-[9px] text-violet-500">{model.sharedOrigin.userName}</span>
                            ) : null}
                            {model.editedVariant?.modelUrl ? (
                              <span className="text-[9px] font-bold uppercase tracking-widest text-emerald-600">已回贴</span>
                            ) : null}
                          </button>

                          {isFailed ? (
                            <span className="text-[9px] text-red-500" title={model.errorMessage ?? '任务失败'}>
                              {model.errorMessage ? (model.errorMessage.length > 72 ? `${model.errorMessage.slice(0, 72)}...` : model.errorMessage) : '失败'}
                            </span>
                          ) : null}

                          {openReviewRoles.length > 0 ? (
                            <>
                              <div className="pointer-events-none absolute left-[calc(100%+0.75rem)] top-0 z-30 hidden w-72 xl:block">
                                <div className="pointer-events-auto space-y-2">
                                  {openReviewRoles.map((role) => (
                                    <Stage2ReviewCommentBubble
                                      key={`${model.resultId}-${role}-desktop`}
                                      role={role}
                                      state={reviewCommentStates![role]}
                                      onClose={() => onCloseReviewComment?.(role)}
                                    />
                                  ))}
                                </div>
                              </div>
                              <div className="pointer-events-none absolute inset-x-2 top-[calc(100%+0.5rem)] z-30 space-y-2 xl:hidden">
                                {openReviewRoles.map((role) => (
                                  <Stage2ReviewCommentBubble
                                    key={`${model.resultId}-${role}-mobile`}
                                    role={role}
                                    state={reviewCommentStates![role]}
                                    onClose={() => onCloseReviewComment?.(role)}
                                  />
                                ))}
                              </div>
                            </>
                          ) : null}
                        </div>
                      );
                    })}

                    {canUploadCustomResult && onUploadCustomTexturedModel && groupIndex === texturedResultGroups.length - 1 ? (
                      <button
                        type="button"
                        onClick={() => setUploadPanelOpen((current) => !current)}
                        className={`flex min-h-[108px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-3 text-center transition-all duration-300 ${
                          uploadPanelOpen
                            ? 'border-blue-300 bg-blue-50 text-blue-700 shadow-sm'
                            : 'border-slate-300 bg-slate-50 text-slate-500 hover:border-blue-300 hover:bg-blue-50/60 hover:text-blue-600'
                        }`}
                        title="上传自定义纹理方案"
                      >
                        <div className={`rounded-full p-2 ${uploadPanelOpen ? 'bg-blue-100' : 'bg-white'}`}>
                          <Plus size={18} />
                        </div>
                        <span className="text-[10px] font-bold uppercase tracking-[0.18em]">
                          {uploadPanelOpen ? '关闭' : '上传'}
                        </span>
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}

              {canUploadCustomResult && onUploadCustomTexturedModel && uploadPanelOpen ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">上传方案</p>
                  <input
                    type="text"
                    value={uploadTitle}
                    onChange={(event) => setUploadTitle(event.target.value)}
                    placeholder="可选方案标题"
                    className="mt-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition focus:border-blue-300"
                  />
                  <div className="mt-3 space-y-2">
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      GLB / GLTF 模型
                      <input
                        type="file"
                        accept=".glb,.gltf,model/gltf-binary,model/gltf+json"
                        onChange={(event) => setUploadModelFile(event.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-[11px] text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-blue-600"
                      />
                    </label>
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Base Color 贴图
                      <input
                        type="file"
                        accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                        onChange={(event) => setUploadBaseColorFile(event.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-[11px] text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-emerald-600"
                      />
                    </label>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <div className="min-w-0 text-[10px] text-slate-500">
                       <p className="truncate">{uploadModelFile ? `模型：${uploadModelFile.name}` : 'GLB / GLTF'}</p>
                       <p className="truncate">{uploadBaseColorFile ? `Base color：${uploadBaseColorFile.name}` : 'Base color 贴图'}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleUploadCustomResult()}
                      disabled={!uploadModelFile || !uploadBaseColorFile || uploadingCustomResult}
                      className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      {uploadingCustomResult ? <LoaderCircle size={12} className="animate-spin" /> : <Plus size={12} />}
                      添加方案
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-3">
              <div className={`grid gap-2 ${canUploadCustomResult && onUploadCustomTexturedModel ? 'grid-cols-4' : 'grid-cols-1'}`}>
                <div className="col-span-3 flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50 py-5 text-center">
                  {textureModelsStatus === 'queued' || textureModelsStatus === 'processing' ? (
                    <>
                      <LoaderCircle size={18} className="animate-spin text-blue-500" />
                      <p className="text-[11px] text-slate-500">
                        {textureModelsStatus === 'queued'
                          ? '已排队。'
                          : '生成中...'}
                      </p>
                    </>
                  ) : textureModelsStatus === 'failed' ? (
                    <>
                      <Box size={18} className="text-red-400" />
                      <p className="text-[11px] text-red-500">生成失败。</p>
                    </>
                  ) : (
                    <>
                      <Sparkles size={18} className="text-slate-400" />
                      <p className="text-[11px] text-slate-500">暂无方案。</p>
                    </>
                  )}
                </div>

                {canUploadCustomResult && onUploadCustomTexturedModel ? (
                  <button
                    type="button"
                    onClick={() => setUploadPanelOpen((current) => !current)}
                    className={`flex min-h-[108px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-3 text-center transition-all duration-300 ${
                      uploadPanelOpen
                        ? 'border-blue-300 bg-blue-50 text-blue-700 shadow-sm'
                        : 'border-slate-300 bg-slate-50 text-slate-500 hover:border-blue-300 hover:bg-blue-50/60 hover:text-blue-600'
                    }`}
                    title="上传自定义纹理方案"
                  >
                    <div className={`rounded-full p-2 ${uploadPanelOpen ? 'bg-blue-100' : 'bg-white'}`}>
                      <Plus size={18} />
                    </div>
                    <span className="text-[10px] font-bold uppercase tracking-[0.18em]">
                          {uploadPanelOpen ? '关闭' : '上传'}
                    </span>
                  </button>
                ) : null}
              </div>

              {canUploadCustomResult && onUploadCustomTexturedModel && uploadPanelOpen ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">上传方案</p>
                  <input
                    type="text"
                    value={uploadTitle}
                    onChange={(event) => setUploadTitle(event.target.value)}
                    placeholder="可选方案标题"
                    className="mt-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition focus:border-blue-300"
                  />
                  <div className="mt-3 space-y-2">
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      GLB / GLTF 模型
                      <input
                        type="file"
                        accept=".glb,.gltf,model/gltf-binary,model/gltf+json"
                        onChange={(event) => setUploadModelFile(event.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-[11px] text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-blue-600"
                      />
                    </label>
                    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      Base Color 贴图
                      <input
                        type="file"
                        accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                        onChange={(event) => setUploadBaseColorFile(event.target.files?.[0] ?? null)}
                        className="mt-1 block w-full text-[11px] text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:px-3 file:py-1.5 file:text-[11px] file:font-semibold file:text-emerald-600"
                      />
                    </label>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <div className="min-w-0 text-[10px] text-slate-500">
                       <p className="truncate">{uploadModelFile ? `模型：${uploadModelFile.name}` : 'GLB / GLTF'}</p>
                       <p className="truncate">{uploadBaseColorFile ? `Base color：${uploadBaseColorFile.name}` : 'Base color 贴图'}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleUploadCustomResult()}
                      disabled={!uploadModelFile || !uploadBaseColorFile || uploadingCustomResult}
                      className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      {uploadingCustomResult ? <LoaderCircle size={12} className="animate-spin" /> : <Plus size={12} />}
                      添加方案
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>

        {completedShareCandidates.length > 0 && onShareResults ? (
          <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">共享</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShareSelectionMode((current) => !current);
                  setSelectedShareResultIds(ownSharedResultIds);
                }}
                className={`inline-flex items-center gap-1 rounded-lg px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] transition ${
                  shareSelectionMode
                    ? 'bg-blue-600 text-white'
                    : 'border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600'
                }`}
              >
                <Share2 size={12} />
                {shareSelectionMode ? '关闭' : '选择'}
              </button>
            </div>

            {shareSelectionMode ? (
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  {completedShareCandidates.map((model) => {
                    const checked = selectedShareResultIds.includes(model.resultId);
                    return (
                      <button
                        key={`share-${model.resultId}`}
                        type="button"
                        onClick={() => handleToggleShareResult(model.resultId)}
                        className={`rounded-xl border px-3 py-2 text-left transition ${
                          checked
                            ? 'border-blue-300 bg-blue-50 text-blue-700'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11px] font-semibold">{model.title || model.resultId}</span>
                          <span className={`h-4 w-4 rounded border ${checked ? 'border-blue-600 bg-blue-600' : 'border-slate-300 bg-white'}`}>
                            {checked ? <Check size={12} className="text-white" /> : null}
                          </span>
                        </div>
                        <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                          {model.sourceType === 'imported' ? '共享导入' : model.schemeId}
                        </p>
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] text-slate-500">
                    {selectedShareResultIds.length > 0
                      ? `已选择 ${selectedShareResultIds.length} 个方案`
                      : '选择方案'}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handlePublishSharedResults()}
                    disabled={sharingResultsPending}
                    className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    {sharingResultsPending ? <LoaderCircle size={12} className="animate-spin" /> : <Users size={12} />}
                    共享
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {ownSharedResultIds.length > 0 ? (
                  ownSharedResultIds.map((resultId) => {
                    const model = completedShareCandidates.find((item) => item.resultId === resultId);
                    if (!model) {
                      return null;
                    }
                    return (
                      <span
                        key={`shared-pill-${resultId}`}
                        className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-600 shadow-sm"
                      >
                        {model.title || model.resultId}
                      </span>
                    );
                  })
                ) : (
                  <span className="text-[10px] text-slate-400">暂无公开方案。</span>
                )}
              </div>
            )}
          </div>
        ) : null}
      </div>

      {sharedResultsViewer?.open ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/35 px-4 py-6 backdrop-blur-sm">
          <div className="flex h-full max-h-[86vh] w-full max-w-7xl overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-2xl">
            <div className="flex w-[22rem] shrink-0 flex-col border-r border-slate-200 bg-slate-50/70">
              <div className="flex h-[5rem] items-center justify-between border-b border-slate-200 bg-white px-5">
                <div>
                  <p className="text-[10px] font-semibold text-slate-500">实时同步</p>
                  <p className="mt-1 text-sm font-bold text-slate-800">{sharedResultsViewer.sourceUserName} 共享方案</p>
                </div>
                <button
                  type="button"
                  className="flex flex-col items-center gap-1 rounded-2xl px-2 py-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                  title="单独对话占位"
                  aria-label="单独对话占位"
                >
                  <MessageCircle size={22} />
                  <span className="text-[8px] font-semibold uppercase tracking-tight">AI单独沟通</span>
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
                {sharedResultsViewer.loading ? (
                  <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-400">
                    <LoaderCircle size={16} className="animate-spin" />
                    加载中...
                  </div>
                ) : sharedResultsViewer.models.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-4 text-center text-sm text-slate-400">
                    暂无共享方案。
                  </div>
                ) : (
                  <div className="space-y-4">
                    {sharedResultsViewer.models.map((model, index) => {
                      const checked = sharedResultsViewer.selectedResultIds.includes(model.resultId);
                      const highlighted = model.resultId === sharedResultsViewer.highlightedResultId;
                      const commenting = sharedCommentingResultId === model.resultId;
                      return (
                        <div
                          key={`sync-${model.resultId}`}
                          className={`rounded-2xl border p-4 shadow-sm transition ${
                            highlighted ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-white'
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => onHighlightSharedResult?.(model.resultId)}
                            className="w-full text-left"
                          >
                            <p className="truncate text-sm font-bold text-slate-800">
                              方案 {String.fromCharCode(65 + index)}：{model.title || model.resultId}
                            </p>
                            <p className="mt-2 text-[11px] text-slate-500">
                              来自 {sharedResultsViewer.sourceUserName} / {model.resultId}
                            </p>
                          </button>
                          <div className="mt-3 flex items-center justify-between gap-2">
                            <button
                              type="button"
                              onClick={() => onToggleSharedResultSelection?.(model.resultId)}
                              className={`inline-flex min-w-16 items-center justify-center rounded-full border px-3 py-1.5 text-[10px] font-semibold transition ${
                                checked
                                  ? 'border-blue-200 bg-blue-600 text-white'
                                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                              }`}
                            >
                              {checked ? '已选择' : '选择'}
                            </button>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setSharedCommentingResultId((current) => (current === model.resultId ? null : model.resultId));
                              }}
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold transition ${
                                commenting ? 'bg-white text-blue-700 ring-1 ring-blue-200' : 'text-slate-400 hover:bg-slate-100 hover:text-slate-600'
                              }`}
                              title="方案评论占位"
                            >
                              <MessageSquare size={12} />
                              评论
                            </button>
                          </div>
                          {commenting ? (
                            <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white/70 px-3 py-2">
                              <input
                                value=""
                                readOnly
                                placeholder="添加评论（占位交互，暂不保存）"
                                className="w-full bg-transparent text-[11px] text-slate-500 outline-none placeholder:text-slate-400"
                              />
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="border-t border-slate-200 bg-white px-4 py-4">
                <button
                  type="button"
                  onClick={() => onImportSharedResults?.()}
                  disabled={sharedResultsViewer.importing || sharedResultsViewer.selectedResultIds.length === 0}
                  className="inline-flex w-full items-center justify-center rounded-2xl border border-blue-500 bg-blue-600 px-4 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none"
                >
                  {sharedResultsViewer.importing ? <LoaderCircle size={15} className="mr-2 animate-spin" /> : null}
                  添加到我的工作区
                </button>
              </div>
            </div>

            <div className="flex min-w-0 flex-1 flex-col bg-white">
              <div className="flex h-[5rem] items-center justify-between border-b border-slate-200 bg-white/95 px-6">
                <p className="text-base font-bold text-slate-800">
                  {sharedPreviewModel ? `方案 / ${sharedPreviewModel.title || sharedPreviewModel.resultId}` : '请选择方案'}
                </p>
                <button
                  type="button"
                  onClick={onCloseSharedResultsViewer}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
                  aria-label="关闭共享方案弹窗"
                >
                  <X size={14} />
                </button>
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto overscroll-contain bg-slate-50/70 p-6">
                <div className="rounded-[1.5rem] border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="grid min-h-[23rem] grid-cols-[minmax(0,1fr)_14.5rem] overflow-hidden rounded-2xl border border-slate-200 bg-white">
                    <div className="relative min-h-0">
                      <div className="absolute left-4 top-4 z-20 rounded-xl border border-slate-200 bg-white/95 px-4 py-2 text-[11px] font-medium text-slate-500 shadow-sm">
                        Orbit / 截图视角
                      </div>
                      {!sharedPreviewModelUrl ? (
                        <div className="flex h-full items-center justify-center text-sm text-slate-400">
                          请选择方案。
                        </div>
                      ) : sharedPreviewUsesRemoteMeshyAsset ? (
                        <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center">
                          <AlertCircle size={24} className="text-amber-500" />
                          <p className="text-sm font-semibold text-slate-700">远程预览不可用</p>
                        </div>
                      ) : (
                        <AppErrorBoundary key={sharedPreviewModelUrl} title="共享 3D 预览失败">
                          <Suspense
                            fallback={
                              <div className="flex h-full items-center justify-center gap-2 text-[11px] font-medium text-slate-400">
                                <LoaderCircle size={14} className="animate-spin" />
                                加载中...
                              </div>
                            }
                          >
                            <Canvas
                              camera={{ position: [4.5, 2.8, 5.8], fov: 42 }}
                              gl={{ preserveDrawingBuffer: true }}
                              onCreated={({ gl }) => {
                                sharedPreviewCanvasRef.current = gl.domElement;
                              }}
                            >
                              <color attach="background" args={['#ffffff']} />
                              <ambientLight intensity={0.9} />
                              <directionalLight intensity={1.15} position={[4, 7, 5]} />
                              <directionalLight intensity={0.45} position={[-3, 4, -4]} />
                              <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.2, 0]} receiveShadow>
                                <planeGeometry args={[20, 20]} />
                                <meshStandardMaterial color="#f1f5f9" />
                              </mesh>
                              <LinkedModelScene
                                key={sharedPreviewModelUrl}
                                modelUrl={sharedPreviewModelUrl}
                                linkedUvFocus={null}
                                onLinkedUvFocusChange={() => undefined}
                                onSelectionChange={() => undefined}
                              />
                              <OrbitControls makeDefault enablePan enableRotate enableZoom />
                            </Canvas>
                          </Suspense>
                        </AppErrorBoundary>
                      )}
                    </div>

                    <div className="relative border-l border-slate-200 bg-slate-50/60">
                      <div className="flex h-12 items-center border-b border-slate-200 px-4">
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50"
                          title="预览评论占位"
                          aria-label="预览评论占位"
                        >
                          <MessageSquare size={12} />
                        </button>
                      </div>
                      <div className="space-y-6 p-4">
                        <div className="h-10 rounded-xl border border-slate-200 bg-white" />
                        <div className="ml-8 h-10 rounded-xl border border-slate-200 bg-white" />
                        <div className="h-10 rounded-xl border border-slate-200 bg-white" />
                      </div>
                      <div className="absolute bottom-0 left-0 right-0 h-16 border-t border-slate-200 bg-white/90">
                        <div className="mx-4 mt-4 h-6 border-l border-slate-200" />
                      </div>
                    </div>
                  </div>
                </div>

                {sharedPreviewModel ? (
                  <div className="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_23rem]">
                      <div>
                        <p className="text-sm font-bold text-slate-800">截图共享预览并生成场景图</p>
                        <p className="mt-2 text-xs text-slate-500">生成结果按 resultId 保存，后续阶段可继续展示。</p>
                        <div className="relative mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                          <label className="block text-[11px] font-medium text-slate-500">
                            场景描述 Prompt
                            <textarea
                              value={sharedScenePrompt}
                              onChange={(event) => setSharedScenePrompt(event.target.value)}
                              rows={3}
                              className="mt-2 w-full resize-none border-0 border-b border-slate-300 bg-transparent px-0 py-1 text-xs font-medium text-slate-700 outline-none focus:border-slate-500"
                            />
                          </label>
                          <button
                            type="button"
                            onClick={() => {
                              void handleGenerateSharedSceneImage();
                            }}
                            disabled={!canGenerateSharedSceneImage || sharedRenderGenerating}
                            className={`absolute bottom-3 right-3 inline-flex items-center justify-center rounded-full border px-4 py-1.5 text-[11px] font-semibold transition ${
                              canGenerateSharedSceneImage && !sharedRenderGenerating
                                ? 'border-blue-500 bg-blue-600 text-white shadow-sm hover:bg-blue-700'
                                : 'cursor-not-allowed border-slate-300 bg-slate-100 text-slate-400'
                            }`}
                          >
                            {sharedRenderGenerating ? '生成中' : '生成'}
                          </button>
                        </div>
                        {sharedPreviewUsesRemoteMeshyAsset ? (
                          <p className="mt-2 text-xs text-amber-600">远程 Meshy 预览暂不能截图，请先使用可本地预览的方案。</p>
                        ) : null}
                        {sharedRenderError ? (
                          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">
                            {sharedRenderError}
                          </div>
                        ) : null}
                      </div>

                      <div>
                        <div className="mb-3 flex items-center justify-between">
                          <p className="text-[11px] font-semibold text-slate-500">已生成</p>
                          {sharedRenderLoading ? <LoaderCircle size={13} className="animate-spin text-slate-400" /> : null}
                        </div>
                        {sharedRenderImages.length > 0 ? (
                          <div className="grid grid-cols-2 gap-3">
                            {sharedRenderImages.slice(0, 4).map((item) => (
                              <button
                                key={item.id}
                                type="button"
                                onClick={() => setSharedRenderLightboxItem(item)}
                                className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
                              >
                                <img src={item.mediaUrl} alt="共享方案已生成渲染图" className="aspect-[4/3] w-full object-cover" />
                                <span className="absolute right-3 top-3 rounded-full bg-black/55 p-1.5 text-white opacity-0 transition group-hover:opacity-100">
                                  <Maximize2 size={12} />
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : (
                          <div className="grid grid-cols-2 gap-3">
                            <div className="aspect-[4/3] rounded-2xl border border-dashed border-slate-200 bg-slate-50" />
                            <div className="aspect-[4/3] rounded-2xl border border-dashed border-slate-200 bg-slate-50" />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {sharedRenderLightboxItem ? (
        <div className="fixed inset-0 z-[95] flex items-center justify-center bg-slate-950/80 p-6 backdrop-blur-sm">
          <div className="relative max-h-full w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-slate-950 shadow-2xl">
            <button
              type="button"
              onClick={() => setSharedRenderLightboxItem(null)}
              className="absolute right-4 top-4 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-slate-700 shadow-sm transition hover:bg-white"
              aria-label="关闭共享方案渲染图预览"
            >
              <X size={16} />
            </button>
            <img src={sharedRenderLightboxItem.mediaUrl} alt="放大的共享方案渲染图" className="max-h-[78vh] w-full object-contain" />
            <div className="flex items-start gap-2 border-t border-white/10 bg-slate-950 px-5 py-3 text-xs leading-5 text-white/70">
              <ImageIcon size={14} className="mt-0.5 shrink-0" />
              <span>{sharedRenderLightboxItem.prompt}</span>
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
};

const Stage2ReviewCommentBubble: React.FC<{
  role: Stage2ReviewRole;
  state: Stage2ReviewCommentState;
  onClose: () => void;
}> = ({ role, state, onClose }) => (
  <div className="pointer-events-auto rounded-2xl border border-slate-200 bg-white/95 p-3 text-left shadow-xl backdrop-blur">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex h-7 w-7 items-center justify-center rounded-full ${
              role === 'engineering' ? 'bg-slate-100 text-slate-700' : 'bg-indigo-100 text-indigo-600'
            }`}
          >
            {role === 'engineering' ? <HardHat size={14} /> : <Users size={14} />}
          </span>
          <div className="min-w-0">
            <p className="truncate text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">{state.label}</p>
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 transition hover:border-slate-300 hover:text-slate-700"
        aria-label={`关闭 ${state.label} 评论`}
      >
        <X size={12} />
      </button>
    </div>
    <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2.5 text-[12px] leading-6 text-slate-700">
      {state.loading ? (
        <span className="inline-flex items-center gap-2 text-slate-500">
          <LoaderCircle size={13} className="animate-spin" />
          加载中...
        </span>
      ) : state.error ? (
        <span className="text-rose-600">{state.error}</span>
      ) : (
        state.comment ?? '暂无评论。'
      )}
    </div>
  </div>
);

const buildTriangleSelection = (mesh: Mesh, faceIndex: number, uvPoint: { u: number; v: number }): TriangleSelection | null => {
  const geometry = mesh.geometry;
  const positionAttribute = geometry.getAttribute('position');
  if (!positionAttribute) {
    return null;
  }

  const triangleIndices = getTriangleIndices(geometry, faceIndex);
  if (!triangleIndices) {
    return null;
  }

  mesh.updateWorldMatrix(true, false);
  const worldMatrix = mesh.matrixWorld ?? new Matrix4();
  const vertices = triangleIndices.map((index) =>
    new Vector3().fromBufferAttribute(positionAttribute, index).applyMatrix4(worldMatrix),
  ) as [Vector3, Vector3, Vector3];

  return {
    meshName: mesh.name || 'unnamed_mesh',
    uv: uvPoint,
    worldVertices: vertices,
  };
};

const findTriangleByUv = (root: Object3D, u: number, v: number): TriangleSelection | null => {
  let found: TriangleSelection | null = null;

  root.traverse((child) => {
    if (found || !(child instanceof Mesh) || !(child.geometry instanceof BufferGeometry)) {
      return;
    }
    const geometry = child.geometry;
    const uvAttribute = geometry.getAttribute('uv');
    const positionAttribute = geometry.getAttribute('position');
    if (!uvAttribute || !positionAttribute) {
      return;
    }

    const triangleCount = geometry.index ? geometry.index.count / 3 : positionAttribute.count / 3;
    for (let faceIndex = 0; faceIndex < triangleCount; faceIndex += 1) {
      const triangleIndices = getTriangleIndices(geometry, faceIndex);
      if (!triangleIndices) {
        continue;
      }
      const a = new Vector2().fromBufferAttribute(uvAttribute, triangleIndices[0]);
      const b = new Vector2().fromBufferAttribute(uvAttribute, triangleIndices[1]);
      const c = new Vector2().fromBufferAttribute(uvAttribute, triangleIndices[2]);
      if (!pointInTriangle(new Vector2(u, v), a, b, c)) {
        continue;
      }
      found = buildTriangleSelection(child, faceIndex, { u, v });
      return;
    }
  });

  return found;
};

const getTriangleIndices = (geometry: BufferGeometry, faceIndex: number): [number, number, number] | null => {
  const start = faceIndex * 3;
  if (geometry.index) {
    const index = geometry.index;
    if (start + 2 >= index.count) {
      return null;
    }
    return [index.getX(start), index.getX(start + 1), index.getX(start + 2)];
  }

  const position = geometry.getAttribute('position');
  if (!position || start + 2 >= position.count) {
    return null;
  }
  return [start, start + 1, start + 2];
};

const pointInTriangle = (point: Vector2, a: Vector2, b: Vector2, c: Vector2): boolean => {
  const denominator = (b.y - c.y) * (a.x - c.x) + (c.x - b.x) * (a.y - c.y);
  if (Math.abs(denominator) < 1e-8) {
    return false;
  }
  const alpha = ((b.y - c.y) * (point.x - c.x) + (c.x - b.x) * (point.y - c.y)) / denominator;
  const beta = ((c.y - a.y) * (point.x - c.x) + (a.x - c.x) * (point.y - c.y)) / denominator;
  const gamma = 1 - alpha - beta;
  return alpha >= -1e-5 && beta >= -1e-5 && gamma >= -1e-5;
};

export default Stage2LinkedPreview;
