import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import {
  AlertCircle,
  ArrowLeft,
  Camera,
  Clapperboard,
  Download,
  ImageIcon,
  Lightbulb,
  LoaderCircle,
  Maximize2,
  PackageOpen,
  Trash2,
  WandSparkles,
  X,
} from 'lucide-react';
import {
  deleteStage4Media,
  fetchStage4Media,
  generateStage4SceneImage,
  generateStage4SceneVideo,
  parseApiError,
  type Stage4MediaAsset,
  type Stage4SceneImageResult,
  type Stage4SceneVideoResult,
} from '../../services/apiClient.ts';
import type { BaseModelMeta, ReviewScheme } from '../../types/design.ts';
import { RECOMMENDATION_CONFIG } from '../../utils/reviewScoring.ts';

interface Stage4PreviewViewProps {
  schemes: ReviewScheme[];
  baseModel: BaseModelMeta | null;
  token: string | null;
  sessionId: number | null;
  isHost?: boolean;
  onRevertToReview?: () => void;
  reverting?: boolean;
  soundEnabled?: boolean;
}

type LightPreset = 'daylight' | 'cloudy' | 'platform' | 'studio';

const PRECISION_LABEL_MAP = {
  authoritative: '精确',
  standard: '标准',
  approximate: '近似',
} as const;

const SOURCE_LABEL_MAP = {
  upload: '上传',
  library: '模型库',
  generate: '生成',
} as const;

const PreviewModelScene: React.FC<{ modelUrl: string }> = ({ modelUrl }) => {
  const { scene } = useGLTF(modelUrl);
  const cloned = useMemo(() => scene.clone(true), [scene]);
  return (
    <Bounds fit clip observe margin={1.15}>
      <primitive object={cloned} />
    </Bounds>
  );
};

const formatCurrency = (value: number): string => `￥${Math.round(value).toLocaleString('zh-CN')}`;

const reviewStateLabel = (status: ReviewScheme['reviewStatus']): string => {
  if (status === 'failed') return '评审失败';
  if (status === 'pending') return '评审中';
  return '评审完成';
};

const Stage4PreviewView: React.FC<Stage4PreviewViewProps> = ({
  schemes,
  baseModel,
  token,
  sessionId,
  isHost = false,
  onRevertToReview,
  reverting = false,
  soundEnabled = true,
}) => {
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>(schemes[0]?.id ?? '');
  const [lightPreset, setLightPreset] = useState<LightPreset>('daylight');
  const [scenePrompt, setScenePrompt] = useState('');
  const [videoPrompt, setVideoPrompt] = useState('');
  const [stage4ImageGenerating, setStage4ImageGenerating] = useState(false);
  const [stage4VideoGenerating, setStage4VideoGenerating] = useState(false);
  const [stage4MediaError, setStage4MediaError] = useState<string | null>(null);
  const [capturedScreenshotUrl, setCapturedScreenshotUrl] = useState<string | null>(null);
  const [stage4ImageResult, setStage4ImageResult] = useState<Stage4SceneImageResult | null>(null);
  const [stage4VideoResult, setStage4VideoResult] = useState<Stage4SceneVideoResult | null>(null);
  const [stage4MediaItems, setStage4MediaItems] = useState<Stage4MediaAsset[]>([]);
  const [stage4MediaLoading, setStage4MediaLoading] = useState(false);
  const [deletingStage4MediaId, setDeletingStage4MediaId] = useState<number | null>(null);
  const [regeneratingStage4MediaId, setRegeneratingStage4MediaId] = useState<number | null>(null);
  const [mediaLightboxItem, setMediaLightboxItem] = useState<Stage4MediaAsset | { mediaType: 'image'; mediaUrl: string; prompt: string } | null>(null);

  useEffect(() => {
    if (schemes.length === 0) {
      setSelectedSchemeId('');
      return;
    }
    if (!schemes.some((scheme) => scheme.id === selectedSchemeId)) {
      setSelectedSchemeId(schemes[0].id);
    }
  }, [schemes, selectedSchemeId]);

  const selectedScheme = useMemo(
    () => schemes.find((scheme) => scheme.id === selectedSchemeId) ?? schemes[0] ?? null,
    [schemes, selectedSchemeId],
  );

  useEffect(() => {
    if (!token || !sessionId || !selectedScheme?.resultId) {
      setStage4MediaItems([]);
      setStage4ImageResult(null);
      setStage4VideoResult(null);
      return;
    }
    let cancelled = false;
    setStage4MediaLoading(true);
    fetchStage4Media(token, { sessionId, resultId: selectedScheme.resultId })
      .then((items) => {
        if (!cancelled) {
          setStage4MediaItems(items);
          const latestImage = items.find((item) => item.mediaType === 'image') ?? null;
          const latestVideo = items.find((item) => item.mediaType === 'video') ?? null;
          setStage4ImageResult(
            latestImage
              ? {
                  sessionId: latestImage.sessionId,
                  resultId: latestImage.resultId,
                  imageUrl: latestImage.mediaUrl,
                  imagePredictionId: latestImage.predictionId ?? '',
                  imagePrompt: latestImage.prompt,
                  createdImage: null,
                  mediaAsset: latestImage,
                }
              : null,
          );
          setStage4VideoResult(
            latestVideo
              ? {
                  sessionId: latestVideo.sessionId,
                  resultId: latestVideo.resultId,
                  videoUrl: latestVideo.mediaUrl,
                  videoPredictionId: latestVideo.predictionId ?? '',
                  videoPrompt: latestVideo.prompt,
                  mediaAsset: latestVideo,
                }
              : null,
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStage4MediaItems([]);
          setStage4ImageResult(null);
          setStage4VideoResult(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setStage4MediaLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedScheme?.resultId, sessionId, token]);

  const lighting = useMemo(() => {
    const presetMap: Record<LightPreset, { intensity: number; envColor: string; directional: number }> = {
      daylight: { intensity: 0.9, envColor: '#dbeafe', directional: 1.2 },
      cloudy: { intensity: 0.65, envColor: '#e2e8f0', directional: 0.8 },
      platform: { intensity: 0.75, envColor: '#fff7ed', directional: 1.0 },
      studio: { intensity: 1.0, envColor: '#f8fafc', directional: 1.3 },
    };
    return presetMap[lightPreset];
  }, [lightPreset]);

  const previewModelUrl = selectedScheme?.texturedModelUrl ?? baseModel?.modelUrl ?? null;
  const previewUsesRemoteMeshy = Boolean(
    previewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(previewModelUrl),
  );
  const recommendation = selectedScheme?.recommendation
    ? RECOMMENDATION_CONFIG[selectedScheme.recommendation]
    : null;
  const hasReviewMetrics = Boolean(
    selectedScheme?.engineering && selectedScheme?.passenger && selectedScheme?.recommendation,
  );
  const canGenerateStage4Image = Boolean(
    token &&
    sessionId &&
    selectedScheme &&
    !previewUsesRemoteMeshy &&
    previewModelUrl &&
    scenePrompt.trim(),
  );
  const canGenerateStage4Video = Boolean(
    token && sessionId && selectedScheme && stage4ImageResult?.imageUrl && videoPrompt.trim(),
  );
  const sortedStage4MediaItems = useMemo(
    () =>
      [...stage4MediaItems].sort((left, right) => {
        if (left.mediaType === right.mediaType) {
          return 0;
        }
        return left.mediaType === 'image' ? -1 : 1;
      }),
    [stage4MediaItems],
  );

  const handleGenerateStage4Image = useCallback(async () => {
    if (!token || !sessionId || !selectedScheme) {
      setStage4MediaError('阶段四媒体生成尚未准备好。');
      return;
    }
    if (previewUsesRemoteMeshy || !previewCanvasRef.current) {
      setStage4MediaError('当前 3D 预览无法截图。');
      return;
    }

    setStage4ImageGenerating(true);
    setStage4MediaError(null);
    try {
      const screenshotDataUrl = previewCanvasRef.current.toDataURL('image/jpeg', 0.92);
      setCapturedScreenshotUrl(screenshotDataUrl);
      setStage4ImageResult(null);
      setStage4VideoResult(null);
      const result = await generateStage4SceneImage(token, {
        sessionId,
        resultId: selectedScheme.resultId,
        schemeName: selectedScheme.name,
        screenshotDataUrl,
        imagePrompt: scenePrompt.trim(),
      });
      setStage4ImageResult(result);
      if (result.mediaAsset) {
        setStage4MediaItems((current) => [result.mediaAsset!, ...current.filter((item) => item.id !== result.mediaAsset!.id)]);
      }
    } catch (error) {
      setStage4MediaError(parseApiError(error, '生成阶段四场景图失败。'));
    } finally {
      setStage4ImageGenerating(false);
    }
  }, [previewUsesRemoteMeshy, scenePrompt, selectedScheme, sessionId, token]);

  const handleRegenerateStage4Image = useCallback(async (item: Stage4MediaAsset) => {
    if (!token || !sessionId || !selectedScheme) {
      setStage4MediaError('阶段四媒体生成尚未准备好。');
      return;
    }
    if (item.mediaType !== 'image') {
      return;
    }
    const prompt = item.prompt.trim() || scenePrompt.trim();
    if (!prompt) {
      setStage4MediaError('缺少可复用的场景描述。');
      return;
    }
    if (previewUsesRemoteMeshy || !previewCanvasRef.current) {
      setStage4MediaError('当前 3D 预览无法截图。');
      return;
    }

    setRegeneratingStage4MediaId(item.id);
    setStage4MediaError(null);
    try {
      const screenshotDataUrl = previewCanvasRef.current.toDataURL('image/jpeg', 0.92);
      setCapturedScreenshotUrl(screenshotDataUrl);
      setStage4VideoResult(null);
      const result = await generateStage4SceneImage(token, {
        sessionId,
        resultId: selectedScheme.resultId,
        schemeName: selectedScheme.name,
        screenshotDataUrl,
        imagePrompt: prompt,
      });
      setStage4ImageResult(result);
      if (result.mediaAsset) {
        setStage4MediaItems((current) => [result.mediaAsset!, ...current.filter((mediaItem) => mediaItem.id !== result.mediaAsset!.id)]);
      }
    } catch (error) {
      setStage4MediaError(parseApiError(error, '再生成阶段四场景图失败。'));
    } finally {
      setRegeneratingStage4MediaId(null);
    }
  }, [previewUsesRemoteMeshy, scenePrompt, selectedScheme, sessionId, token]);

  const handleGenerateStage4Video = useCallback(async () => {
    if (!token || !sessionId || !selectedScheme || !stage4ImageResult?.imageUrl) {
      setStage4MediaError('请先生成场景图，再生成视频。');
      return;
    }

    setStage4VideoGenerating(true);
    setStage4MediaError(null);
    try {
      const result = await generateStage4SceneVideo(token, {
        sessionId,
        resultId: selectedScheme.resultId,
        schemeName: selectedScheme.name,
        imageUrl: stage4ImageResult.imageUrl,
        videoPrompt: videoPrompt.trim(),
        duration: 4,
        resolution: '480p',
        generateAudio: true,
      });
      setStage4VideoResult(result);
      if (result.mediaAsset) {
        setStage4MediaItems((current) => [result.mediaAsset!, ...current.filter((item) => item.id !== result.mediaAsset!.id)]);
      }
    } catch (error) {
      setStage4MediaError(parseApiError(error, '生成阶段四视频失败。'));
    } finally {
      setStage4VideoGenerating(false);
    }
  }, [selectedScheme, sessionId, stage4ImageResult?.imageUrl, token, videoPrompt]);

  const handleDeleteStage4Media = useCallback(async (item: Stage4MediaAsset) => {
    if (!token || !sessionId) {
      setStage4MediaError('阶段四媒体删除尚未准备好。');
      return;
    }

    const confirmed = window.confirm(
      `确定删除这张已生成的${item.mediaType === 'image' ? '图片' : '视频'}吗？删除后无法恢复。`,
    );
    if (!confirmed) {
      return;
    }

    setDeletingStage4MediaId(item.id);
    setStage4MediaError(null);
    try {
      await deleteStage4Media(token, {
        sessionId,
        assetId: item.id,
      });
      setStage4MediaItems((current) => current.filter((mediaItem) => mediaItem.id !== item.id));
      setStage4ImageResult((current) => {
        if (!current) {
          return current;
        }
        return current.mediaAsset?.id === item.id || current.imageUrl === item.mediaUrl ? null : current;
      });
      setStage4VideoResult((current) => {
        if (!current) {
          return current;
        }
        return current.mediaAsset?.id === item.id || current.videoUrl === item.mediaUrl ? null : current;
      });
      setMediaLightboxItem((current) => {
        if (!current) {
          return current;
        }
        return 'id' in current && current.id === item.id ? null : current;
      });
    } catch (error) {
      setStage4MediaError(parseApiError(error, '删除阶段四媒体失败。'));
    } finally {
      setDeletingStage4MediaId(null);
    }
  }, [sessionId, token]);

  if (!baseModel || !selectedScheme) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-slate-50 text-slate-500">
        <p>暂无定稿候选方案。</p>
        {isHost && onRevertToReview ? (
          <button
            type="button"
            onClick={onRevertToReview}
            disabled={reverting}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            {reverting ? <LoaderCircle size={14} className="animate-spin" /> : <ArrowLeft size={14} />}
            返回
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-1 overflow-hidden bg-slate-50">
      <div className="min-h-0 min-w-0 flex-1 p-4">
        <div className="relative h-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          {previewUsesRemoteMeshy ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
              <div className="rounded-2xl bg-amber-50 p-4 text-amber-500">
                <AlertCircle size={24} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">远程预览不可用</p>
              </div>
              {selectedScheme.baseColorTextureUrl ? (
                <img
                  src={selectedScheme.baseColorTextureUrl}
                  alt={`${selectedScheme.name} texture`}
                  className="h-32 rounded-2xl border border-slate-200 object-contain"
                />
              ) : null}
            </div>
          ) : previewModelUrl ? (
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                  <LoaderCircle size={16} className="animate-spin" />
                  加载中...
                </div>
              }
            >
              <Canvas
                shadows
                camera={{ position: [9, 4, 9], fov: 42 }}
                gl={{ preserveDrawingBuffer: true }}
                onCreated={({ gl }) => {
                  previewCanvasRef.current = gl.domElement;
                }}
              >
                <color attach="background" args={[lighting.envColor]} />
                <ambientLight intensity={lighting.intensity} />
                <directionalLight
                  intensity={lighting.directional}
                  position={[5, 8, 5]}
                  castShadow
                  shadow-mapSize-width={1024}
                  shadow-mapSize-height={1024}
                />
                <directionalLight intensity={0.45} position={[-5, 4, -5]} />
                <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.2, 0]} receiveShadow>
                  <planeGeometry args={[30, 30]} />
                  <meshStandardMaterial color="#e2e8f0" />
                </mesh>
                <PreviewModelScene key={previewModelUrl} modelUrl={previewModelUrl} />
                <OrbitControls makeDefault enablePan enableZoom enableRotate />
              </Canvas>
            </Suspense>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              暂无预览。
            </div>
          )}

          <div className="absolute left-4 top-4 rounded-xl border border-slate-200 bg-white/95 p-4 text-xs shadow-sm backdrop-blur transition-all">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">基础模型</p>
            <div className="mt-2 space-y-1 text-slate-700">
              <p><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">ID</span>: {baseModel.baseModelId}</p>
              <p><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">来源</span>: {SOURCE_LABEL_MAP[baseModel.sourceType]}</p>
              <p><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">精度</span>: {PRECISION_LABEL_MAP[baseModel.precisionLevel]}</p>
            </div>
          </div>

          <div className="absolute right-4 top-4 rounded-xl border border-slate-200 bg-white/95 p-4 text-xs shadow-sm backdrop-blur transition-all">
            <div className="mb-2 flex items-center gap-1.5 text-slate-600">
              <Lightbulb size={13} />
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">灯光</span>
            </div>
            <div className="grid grid-cols-2 gap-1">
              {(['daylight', 'cloudy', 'platform', 'studio'] as LightPreset[]).map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setLightPreset(preset)}
                  className={`rounded-md px-2 py-1 text-[11px] font-semibold transition ${
                    preset === lightPreset
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100'
                  }`}
                >
                  {{ daylight: '日光', cloudy: '阴天', platform: '站台', studio: '影棚' }[preset]}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <aside className="z-20 flex min-h-0 w-96 shrink-0 flex-col overflow-y-auto overscroll-contain border-l border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">S4</p>
            <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-slate-800">最终预览</h3>
          </div>
          {isHost && onRevertToReview ? (
            <button
              type="button"
              onClick={onRevertToReview}
              disabled={reverting}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-blue-600 transition hover:bg-blue-100 disabled:opacity-50"
            >
              {reverting ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowLeft size={13} />}
              返回
            </button>
          ) : null}
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-600">媒体智能体</p>
            </div>
            <WandSparkles size={16} className="shrink-0 text-blue-500" />
          </div>

          <label className="block text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
            场景
            <textarea
              value={scenePrompt}
              onChange={(event) => setScenePrompt(event.target.value)}
              placeholder="描述高铁所在的运行场景"
              rows={3}
              className="mt-1 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium normal-case tracking-normal text-slate-700 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
            />
          </label>

          <button
            type="button"
            onClick={() => {
              void handleGenerateStage4Image();
            }}
            disabled={!canGenerateStage4Image || stage4ImageGenerating}
            className={`mt-3 flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-bold uppercase tracking-wider transition ${
              canGenerateStage4Image && !stage4ImageGenerating
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'cursor-not-allowed bg-slate-200 text-slate-400'
            }`}
          >
            {stage4ImageGenerating ? <LoaderCircle size={14} className="animate-spin" /> : <Camera size={14} />}
            {stage4ImageGenerating ? '生成图片中' : '生成图片'}
          </button>

          {stage4MediaError ? (
            <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700">
              {stage4MediaError}
            </div>
          ) : null}

          {capturedScreenshotUrl || stage4ImageResult ? (
            <div className="mt-3 grid grid-cols-2 gap-2">
              {capturedScreenshotUrl ? (
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                  <div className="flex items-center gap-1.5 border-b border-slate-100 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    <Camera size={11} />
                    视角
                  </div>
                  <img src={capturedScreenshotUrl} alt="已截图的 3D 预览" className="aspect-video w-full object-cover" />
                </div>
              ) : null}
              {stage4ImageResult ? (
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                  <div className="flex items-center gap-1.5 border-b border-slate-100 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    <ImageIcon size={11} />
                    场景图
                  </div>
                  <img src={stage4ImageResult.imageUrl} alt="生成的高铁场景图" className="aspect-video w-full object-cover" />
                </div>
              ) : null}
            </div>
          ) : null}

          {stage4ImageResult ? (
            <>
              <label className="mt-3 block text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                视频
                <textarea
                  value={videoPrompt}
                  onChange={(event) => setVideoPrompt(event.target.value)}
                  placeholder="描述视频运动、镜头和氛围"
                  rows={3}
                  className="mt-1 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium normal-case tracking-normal text-slate-700 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                />
              </label>

              <button
                type="button"
                onClick={() => {
                  void handleGenerateStage4Video();
                }}
                disabled={!canGenerateStage4Video || stage4VideoGenerating}
                className={`mt-3 flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-bold uppercase tracking-wider transition ${
                  canGenerateStage4Video && !stage4VideoGenerating
                    ? 'bg-slate-900 text-white hover:bg-slate-800'
                    : 'cursor-not-allowed bg-slate-200 text-slate-400'
                }`}
              >
                {stage4VideoGenerating ? <LoaderCircle size={14} className="animate-spin" /> : <Clapperboard size={14} />}
                {stage4VideoGenerating ? '生成视频中' : '生成视频'}
              </button>
            </>
          ) : null}

          {stage4VideoResult ? (
            <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-black">
              <div className="flex items-center gap-1.5 border-b border-white/10 bg-slate-950 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-white/70">
                <Clapperboard size={12} />
                视频
              </div>
              <video src={stage4VideoResult.videoUrl} controls muted={!soundEnabled} className="aspect-video w-full bg-black" />
            </div>
          ) : null}

          <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">已生成渲染图/视频</p>
              {stage4MediaLoading ? <LoaderCircle size={13} className="animate-spin text-slate-400" /> : null}
            </div>
            {sortedStage4MediaItems.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {sortedStage4MediaItems.map((item) => (
                  <div key={item.id} className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                    <button
                      type="button"
                      onClick={() => setMediaLightboxItem(item)}
                      className="group relative block w-full"
                    >
                      {item.mediaType === 'image' ? (
                        <img src={item.mediaUrl} alt="已保存场景图" className="aspect-video w-full object-cover" />
                      ) : (
                        <video src={item.mediaUrl} muted={!soundEnabled} className="aspect-video w-full bg-black object-cover" />
                      )}
                      <span className="absolute right-2 top-2 rounded-full bg-black/55 p-1 text-white opacity-0 transition group-hover:opacity-100">
                        <Maximize2 size={12} />
                      </span>
                    </button>
                    <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                      <span className="text-[10px] font-semibold text-slate-500">
                        {item.mediaType === 'image' ? '渲染图' : '视频'}
                      </span>
                      <div className="flex items-center gap-1.5">
                        {item.mediaType === 'image' ? (
                          <>
                            <button
                              type="button"
                              onClick={() => {
                                void handleRegenerateStage4Image(item);
                              }}
                              disabled={regeneratingStage4MediaId !== null || stage4ImageGenerating || previewUsesRemoteMeshy}
                              className={`rounded-md px-2 py-1 text-[10px] font-semibold transition ${
                                regeneratingStage4MediaId !== null || stage4ImageGenerating || previewUsesRemoteMeshy
                                  ? 'cursor-not-allowed bg-slate-100 text-slate-400'
                                  : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                              }`}
                            >
                              {regeneratingStage4MediaId === item.id ? '生成中' : '再生成'}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setStage4ImageResult({
                                  sessionId: sessionId ?? 0,
                                  resultId: item.resultId,
                                  imageUrl: item.mediaUrl,
                                  imagePredictionId: item.predictionId ?? '',
                                  imagePrompt: item.prompt,
                                  createdImage: null,
                                  mediaAsset: item,
                                });
                                setStage4VideoResult(null);
                              }}
                              className="rounded-md bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-700 hover:bg-blue-100"
                            >
                              设为首帧
                            </button>
                          </>
                        ) : null}
                        {item.canDelete ? (
                          <button
                            type="button"
                            onClick={() => {
                              void handleDeleteStage4Media(item);
                            }}
                            disabled={deletingStage4MediaId === item.id}
                            className={`inline-flex h-7 w-7 items-center justify-center rounded-md border transition ${
                              deletingStage4MediaId === item.id
                                ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                                : 'border-slate-200 bg-white text-slate-400 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600'
                            }`}
                            title="删除该媒体"
                            aria-label={`删除阶段四${item.mediaType === 'image' ? '图片' : '视频'}`}
                          >
                            {deletingStage4MediaId === item.id ? (
                              <LoaderCircle size={12} className="animate-spin" />
                            ) : (
                              <Trash2 size={12} />
                            )}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500">暂无保存的图片或视频。</p>
            )}
          </div>
        </div>

        <div className="mb-4 space-y-3">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">候选方案</p>
          {schemes.map((scheme) => {
            const schemeRecommendation = scheme.recommendation ? RECOMMENDATION_CONFIG[scheme.recommendation] : null;
            return (
              <button
                key={scheme.id}
                type="button"
                onClick={() => setSelectedSchemeId(scheme.id)}
                className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                  scheme.id === selectedScheme.id
                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                    : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{scheme.name}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {scheme.submittedByName ?? scheme.author}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {scheme.engineering ? formatCurrency(scheme.engineering.totalCostYuan) : '暂无指标'}
                    </p>
                    {scheme.reviewSettingsStale ? (
                      <p className="mt-1 text-xs font-semibold text-amber-700">评审已过期</p>
                    ) : null}
                  </div>
                  {schemeRecommendation ? (
                    <span
                      className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold ${schemeRecommendation.bgColor} ${schemeRecommendation.color}`}
                    >
                      {schemeRecommendation.label}
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-full border border-slate-200 bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">
                      {reviewStateLabel(scheme.reviewStatus)}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50/50 p-4 text-sm text-slate-700 shadow-sm">
          <p className="mb-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{selectedScheme.engineeringLabel}</p>
          {selectedScheme.engineering ? (
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] font-semibold text-slate-800">
              <p className="flex justify-between items-center"><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">油漆</span> <span>{selectedScheme.engineering.paintVolumeKg.toFixed(1)} kg</span></p>
              <p className="flex justify-between items-center"><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">总成本</span> <span>{formatCurrency(selectedScheme.engineering.totalCostYuan)}</span></p>
              <p className="flex justify-between items-center"><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">工时</span> <span>{selectedScheme.engineering.laborHours} h</span></p>
              <p className="flex justify-between items-center"><span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">风险</span> <span>{selectedScheme.engineering.colorVarianceRisk}</span></p>
            </div>
          ) : (
            <p className="p-2 text-center text-xs text-slate-500">暂无指标。</p>
          )}
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{selectedScheme.passengerLabel}</p>
          {selectedScheme.passenger ? (
            <>
              {selectedScheme.reviewSettingsStale ? (
                <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  评审版本 {selectedScheme.reviewSettingsRevisionUsed ?? '上一版'}。
                </div>
              ) : null}
              <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/50 p-4">
                <div className="flex flex-col gap-4 min-[420px]:flex-row min-[420px]:items-start min-[420px]:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 text-center min-[420px]:text-left">总体印象</p>
                    <p className="mt-2 break-words text-[13px] font-medium leading-[1.62] text-slate-700">{selectedScheme.passenger.summary}</p>
                  </div>
                  <div className="shrink-0 rounded-xl bg-white px-3 py-2 text-center shadow-sm min-[420px]:w-20">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">分数</p>
                    <p className="mt-0.5 text-2xl font-extrabold tracking-tighter text-blue-900">{selectedScheme.passenger.overallScore.toFixed(1)}</p>
                    <p className="text-[10px] font-bold text-slate-400">/ 10</p>
                  </div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-700">
                <PreviewMetric label="第一印象" value={selectedScheme.passenger.scores.firstImpression} />
                <PreviewMetric label="安全信任" value={selectedScheme.passenger.scores.safetyTrust} />
                <PreviewMetric label="舒适整洁" value={selectedScheme.passenger.scores.comfortCleanliness} />
                <PreviewMetric label="品质感" value={selectedScheme.passenger.scores.perceivedQuality} />
                <PreviewMetric label="速度感" value={selectedScheme.passenger.scores.speedMotion} />
                <PreviewMetric label="情感性格" value={selectedScheme.passenger.scores.emotionCharacter} />
              </div>
            </>
          ) : (
            <p className="mt-3 text-sm text-slate-600">暂无乘客评审指标。</p>
          )}
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <p className="font-semibold text-slate-800">决策</p>
          <p className="mt-1">
            {recommendation?.label ?? (selectedScheme.reviewStatus === 'failed' ? '评审不可用' : '等待建议')}
          </p>
          {!hasReviewMetrics && selectedScheme.reviewStatus === 'failed' ? (
            <p className="mt-1 text-xs text-rose-600">
              {selectedScheme.reviewErrorMessage || '该方案的阶段三评审失败。'}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-slate-500">{selectedScheme.starredBy.length} 个收藏</p>
        </div>

        <div className="mt-auto space-y-2 pt-4 border-t border-slate-100">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">导出</p>
          <ActionButton label="导出 UV 布局 (PNG)" icon={<Download size={14} />} />
          <ActionButton label="导出工程报告 (PDF)" icon={<Download size={14} />} />
          <ActionButton label="导出 3D 截图" icon={<Camera size={14} />} />

          {baseModel.exportGlbAllowed ? (
            <ActionButton label="导出纹理 GLB" icon={<PackageOpen size={14} />} />
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
              该模型的 GLB 导出受限。
            </div>
          )}

          {!baseModel.exportGlbAllowed ? (
            <ActionButton label="导出预览包" icon={<PackageOpen size={14} />} />
          ) : null}
        </div>
      </aside>
      {mediaLightboxItem ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/80 p-6 backdrop-blur-sm">
          <div className="relative max-h-full w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-slate-950 shadow-2xl">
            <button
              type="button"
              onClick={() => setMediaLightboxItem(null)}
              className="absolute right-4 top-4 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-slate-700 shadow-sm transition hover:bg-white"
              aria-label="关闭预览"
            >
              <X size={16} />
            </button>
            {mediaLightboxItem.mediaType === 'image' ? (
              <img src={mediaLightboxItem.mediaUrl} alt="放大的阶段四图片" className="max-h-[78vh] w-full object-contain" />
            ) : (
              <video
                src={mediaLightboxItem.mediaUrl}
                controls
                autoPlay
                muted={!soundEnabled}
                className="max-h-[78vh] w-full bg-black"
              />
            )}
            <div className="border-t border-white/10 bg-slate-950 px-5 py-3 text-xs leading-5 text-white/70">
              {mediaLightboxItem.prompt}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const PreviewMetric: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <div className="rounded-xl border border-slate-100 bg-slate-50/50 px-3 py-2.5">
    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
    <p className="mt-1 text-sm font-semibold text-slate-800">{value}</p>
  </div>
);

const ActionButton: React.FC<{ label: string; icon: React.ReactNode }> = ({ label, icon }) => (
  <button
    type="button"
    className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-[11px] font-bold uppercase tracking-wider text-slate-700 transition-all hover:bg-slate-50 hover:border-slate-300 hover:shadow-sm"
  >
    {icon}
    {label}
  </button>
);

export default Stage4PreviewView;
