import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Box,
  Camera,
  ChevronDown,
  ImageIcon,
  Layers3,
  Lightbulb,
  LoaderCircle,
  Maximize2,
  RefreshCw,
  Star,
  HardHat,
  Users,
  X,
} from 'lucide-react';
import {
  fetchSceneRenderMedia,
  parseApiError,
  type Stage4MediaAsset,
} from '../../services/apiClient.ts';
import type { BaseModelMeta, ReviewScheme } from '../../types/design.ts';
import { RECOMMENDATION_CONFIG } from '../../utils/reviewScoring.ts';
import AppErrorBoundary from '../AppErrorBoundary.tsx';

interface Stage3ReviewViewProps {
  schemes: ReviewScheme[];
  baseModel: BaseModelMeta | null;
  token?: string | null;
  sessionId?: number | null;
  isHost: boolean;
  currentUserId: string;
  onStarScheme: (resultId: string) => void;
  onRefreshReview?: (resultId: string) => void;
  onRevertToDesign?: () => void;
  refreshingReviewSchemeId?: string | null;
  reverting?: boolean;
}

type LightPreset =
  | 'daylight'
  | 'cloudy'
  | 'studio'
  | 'platform'
  | 'sunset'
  | 'dramatic'
  | 'inspection'
  | 'night';

type ReviewTab = 'passenger' | 'engineering';
type SchemeGroup = {
  familyId: string;
  title: string;
  memberSummary: string;
  schemes: ReviewScheme[];
};

type LightingProfile = {
  label: string;
  hint: string;
  bg: string;
  ground: string;
  ambient: number;
  hemisphere: number;
  hemisphereSky: string;
  hemisphereGround: string;
  key: number;
  keyColor: string;
  keyPosition: [number, number, number];
  fill: number;
  fillColor: string;
  fillPosition: [number, number, number];
  rim: number;
  rimColor: string;
  rimPosition: [number, number, number];
  spot: number;
  spotColor: string;
  spotPosition: [number, number, number];
};

const LIGHTING_PRESETS: Record<LightPreset, LightingProfile> = {
  daylight: {
    label: '日光',
    hint: '均衡的外观评审光照',
    bg: '#f8fafc',
    ground: '#e2e8f0',
    ambient: 0.9,
    hemisphere: 0.35,
    hemisphereSky: '#f8fbff',
    hemisphereGround: '#cbd5e1',
    key: 1.15,
    keyColor: '#fff7ed',
    keyPosition: [6, 8, 6],
    fill: 0.42,
    fillColor: '#dbeafe',
    fillPosition: [-6, 5, -4],
    rim: 0.22,
    rimColor: '#e0f2fe',
    rimPosition: [0, 6, -7],
    spot: 0.12,
    spotColor: '#ffffff',
    spotPosition: [0, 10, 0],
  },
  cloudy: {
    label: '阴天',
    hint: '柔和漫射的表面检查',
    bg: '#eef2f7',
    ground: '#dde5ef',
    ambient: 1.02,
    hemisphere: 0.4,
    hemisphereSky: '#f8fafc',
    hemisphereGround: '#dbe4ef',
    key: 0.76,
    keyColor: '#f8fafc',
    keyPosition: [5, 8, 5],
    fill: 0.38,
    fillColor: '#e2e8f0',
    fillPosition: [-5, 4, -4],
    rim: 0.12,
    rimColor: '#f1f5f9',
    rimPosition: [0, 5, -6],
    spot: 0.08,
    spotColor: '#ffffff',
    spotPosition: [0, 9, 0],
  },
  studio: {
    label: '影棚',
    hint: '更清晰的涂装对比',
    bg: '#f6f7fb',
    ground: '#d8dee8',
    ambient: 0.72,
    hemisphere: 0.28,
    hemisphereSky: '#f8fafc',
    hemisphereGround: '#cbd5e1',
    key: 1.34,
    keyColor: '#fffaf0',
    keyPosition: [7, 8, 5],
    fill: 0.62,
    fillColor: '#dbeafe',
    fillPosition: [-7, 4, -3],
    rim: 0.35,
    rimColor: '#bfdbfe',
    rimPosition: [0, 7, -7],
    spot: 0.18,
    spotColor: '#ffffff',
    spotPosition: [0, 10, 3],
  },
  platform: {
    label: '站台',
    hint: '类似车站的冷暖混合光',
    bg: '#f8fafc',
    ground: '#d7dee8',
    ambient: 0.74,
    hemisphere: 0.26,
    hemisphereSky: '#e0f2fe',
    hemisphereGround: '#fde68a',
    key: 1.08,
    keyColor: '#fff7ed',
    keyPosition: [6, 7, 4],
    fill: 0.48,
    fillColor: '#dbeafe',
    fillPosition: [-6, 4, -5],
    rim: 0.26,
    rimColor: '#fef3c7',
    rimPosition: [0, 6, -6],
    spot: 0.14,
    spotColor: '#fff7ed',
    spotPosition: [0, 9, 2],
  },
  sunset: {
    label: '夕阳',
    hint: '温暖的边缘高光',
    bg: '#fff2e8',
    ground: '#f2d4bf',
    ambient: 0.72,
    hemisphere: 0.24,
    hemisphereSky: '#ffedd5',
    hemisphereGround: '#fdba74',
    key: 1.18,
    keyColor: '#fb923c',
    keyPosition: [7, 6, 4],
    fill: 0.46,
    fillColor: '#fed7aa',
    fillPosition: [-5, 4, -3],
    rim: 0.4,
    rimColor: '#f59e0b',
    rimPosition: [0, 6, -7],
    spot: 0.14,
    spotColor: '#fdba74',
    spotPosition: [0, 8, 2],
  },
  dramatic: {
    label: '高反差',
    hint: '用于观察轮廓的高对比光',
    bg: '#edf2f7',
    ground: '#cbd5e1',
    ambient: 0.44,
    hemisphere: 0.18,
    hemisphereSky: '#e2e8f0',
    hemisphereGround: '#94a3b8',
    key: 1.52,
    keyColor: '#ffffff',
    keyPosition: [7, 8, 3],
    fill: 0.16,
    fillColor: '#bfdbfe',
    fillPosition: [-6, 3, -5],
    rim: 0.54,
    rimColor: '#93c5fd',
    rimPosition: [0, 7, -8],
    spot: 0.2,
    spotColor: '#ffffff',
    spotPosition: [0, 10, 1],
  },
  inspection: {
    label: '检测',
    hint: '用于表面缺陷检查的中性光',
    bg: '#f8fafc',
    ground: '#dbe2ea',
    ambient: 0.88,
    hemisphere: 0.33,
    hemisphereSky: '#ffffff',
    hemisphereGround: '#cbd5e1',
    key: 1.28,
    keyColor: '#ffffff',
    keyPosition: [5, 9, 4],
    fill: 0.55,
    fillColor: '#f8fafc',
    fillPosition: [-5, 5, -4],
    rim: 0.2,
    rimColor: '#e2e8f0',
    rimPosition: [0, 6, -6],
    spot: 0.18,
    spotColor: '#ffffff',
    spotPosition: [0, 10, 0],
  },
  night: {
    label: '夜间',
    hint: '低环境光与冷色轮廓光',
    bg: '#0f172a',
    ground: '#1e293b',
    ambient: 0.22,
    hemisphere: 0.12,
    hemisphereSky: '#1d4ed8',
    hemisphereGround: '#0f172a',
    key: 0.82,
    keyColor: '#dbeafe',
    keyPosition: [6, 8, 5],
    fill: 0.12,
    fillColor: '#38bdf8',
    fillPosition: [-5, 3, -4],
    rim: 0.62,
    rimColor: '#67e8f9',
    rimPosition: [0, 7, -8],
    spot: 0.1,
    spotColor: '#93c5fd',
    spotPosition: [0, 10, 2],
  },
};

const ReviewModelScene: React.FC<{ modelUrl: string }> = ({ modelUrl }) => {
  const { scene } = useGLTF(modelUrl);
  const cloned = useMemo(() => {
    const nextScene = scene.clone(true);
    nextScene.traverse((object) => {
      const mesh = object as {
        isMesh?: boolean;
        castShadow?: boolean;
        receiveShadow?: boolean;
      };
      if (!mesh.isMesh) {
        return;
      }
      mesh.castShadow = true;
      mesh.receiveShadow = true;
    });
    return nextScene;
  }, [scene]);
  return (
    <Bounds fit clip observe margin={1.15}>
      <primitive object={cloned} />
    </Bounds>
  );
};

const formatCurrency = (value: number): string => `￥${Math.round(value).toLocaleString('zh-CN')}`;

const riskBadgeClass = (level: string): string => {
  if (level === 'HIGH') return 'bg-rose-100 text-rose-700';
  if (level === 'MEDIUM') return 'bg-amber-100 text-amber-700';
  return 'bg-emerald-100 text-emerald-700';
};

const durabilityBadgeClass = (grade: string): string => {
  if (grade === 'A') return 'bg-emerald-100 text-emerald-700';
  if (grade === 'B') return 'bg-amber-100 text-amber-700';
  return 'bg-rose-100 text-rose-700';
};

// Removing unused passengerBarClass

const reviewStateBadgeClass = (status: ReviewScheme['reviewStatus']): string => {
  if (status === 'failed') return 'border-rose-200 bg-rose-50 text-rose-700';
  if (status === 'pending') return 'border-slate-200 bg-slate-100 text-slate-600';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700';
};

const reviewStateLabel = (status: ReviewScheme['reviewStatus']): string => {
  if (status === 'failed') return '评审失败';
  if (status === 'pending') return '评审中';
  return '评审完成';
};

const createdAtValue = (value: string): number => {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const isFamilyRoot = (scheme: ReviewScheme, familySchemes: ReviewScheme[]): boolean => {
  if (!scheme.parentResultId) {
    return true;
  }
  return !familySchemes.some((candidate) => candidate.resultId === scheme.parentResultId);
};

const Stage3ReviewView: React.FC<Stage3ReviewViewProps> = ({
  schemes,
  baseModel,
  token = null,
  sessionId = null,
  isHost,
  currentUserId,
  onStarScheme,
  onRefreshReview,
  onRevertToDesign,
  refreshingReviewSchemeId = null,
  reverting = false,
}) => {
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>(schemes[0]?.id ?? '');
  const [lightPreset, setLightPreset] = useState<LightPreset>('daylight');
  const [lightStrength, setLightStrength] = useState<number>(100);
  const [shadowsEnabled, setShadowsEnabled] = useState<boolean>(true);
  const [lightingPanelExpanded, setLightingPanelExpanded] = useState(false);
  const [activeReviewTab, setActiveReviewTab] = useState<ReviewTab>('passenger');
  const [analysisPanelExpanded, setAnalysisPanelExpanded] = useState(true);
  const [sceneRenderWindowOpen, setSceneRenderWindowOpen] = useState(false);
  const [sceneRenderMediaItems, setSceneRenderMediaItems] = useState<Stage4MediaAsset[]>([]);
  const [sceneRenderLoading, setSceneRenderLoading] = useState(false);
  const [sceneRenderError, setSceneRenderError] = useState<string | null>(null);
  const [sceneRenderLightboxItem, setSceneRenderLightboxItem] = useState<Stage4MediaAsset | null>(null);

  const selectedScheme = useMemo(
    () => schemes.find((scheme) => scheme.id === selectedSchemeId) ?? schemes[0] ?? null,
    [schemes, selectedSchemeId],
  );
  const groupedSchemes = useMemo<SchemeGroup[]>(() => {
    const families = new Map<string, ReviewScheme[]>();
    for (const scheme of schemes) {
      const familyId = scheme.familyId || scheme.resultId;
      const family = families.get(familyId);
      if (family) {
        family.push(scheme);
      } else {
        families.set(familyId, [scheme]);
      }
    }

    return [...families.entries()]
      .map(([familyId, familySchemes]) => {
        const sortedSchemes = [...familySchemes].sort((left, right) => {
          const leftIsRoot = isFamilyRoot(left, familySchemes);
          const rightIsRoot = isFamilyRoot(right, familySchemes);
          if (leftIsRoot !== rightIsRoot) {
            return leftIsRoot ? -1 : 1;
          }
          return createdAtValue(left.createdAt) - createdAtValue(right.createdAt);
        });
        const rootScheme = sortedSchemes.find((scheme) => isFamilyRoot(scheme, familySchemes)) ?? sortedSchemes[0];
        const memberSummary = [...new Set(sortedSchemes.map((scheme) => scheme.submittedByName ?? scheme.author))]
          .filter((item) => item.trim().length > 0)
          .join(' / ');
        return {
          familyId,
          title: rootScheme.groupTitle || rootScheme.name,
          memberSummary,
          schemes: sortedSchemes,
        };
      })
      .sort((left, right) => createdAtValue(left.schemes[0]?.createdAt ?? '') - createdAtValue(right.schemes[0]?.createdAt ?? ''));
  }, [schemes]);
  const selectedGroup = useMemo(
    () => groupedSchemes.find((group) => group.familyId === (selectedScheme?.familyId || selectedScheme?.resultId)),
    [groupedSchemes, selectedScheme],
  );
  const reviewResultIds = useMemo(() => new Set(schemes.map((scheme) => scheme.resultId)), [schemes]);
  const sceneRenderImagesByResultId = useMemo(() => {
    const imagesByResultId = new Map<string, Stage4MediaAsset[]>();
    for (const item of sceneRenderMediaItems) {
      if (item.mediaType !== 'image' || !item.resultId || !reviewResultIds.has(item.resultId)) {
        continue;
      }
      const existing = imagesByResultId.get(item.resultId);
      if (existing) {
        existing.push(item);
      } else {
        imagesByResultId.set(item.resultId, [item]);
      }
    }
    return imagesByResultId;
  }, [reviewResultIds, sceneRenderMediaItems]);
  const sceneRenderImageCount = useMemo(
    () => [...sceneRenderImagesByResultId.values()].reduce((total, items) => total + items.length, 0),
    [sceneRenderImagesByResultId],
  );

  const loadSceneRenderMedia = useCallback(async () => {
    if (!token || !sessionId) {
      setSceneRenderMediaItems([]);
      return;
    }
    setSceneRenderLoading(true);
    setSceneRenderError(null);
    try {
      const items = await fetchSceneRenderMedia(token, { sessionId });
      setSceneRenderMediaItems(items.filter((item) => item.mediaType === 'image'));
    } catch (error) {
      setSceneRenderMediaItems([]);
      setSceneRenderError(parseApiError(error, '加载场景渲染图失败。'));
    } finally {
      setSceneRenderLoading(false);
    }
  }, [sessionId, token]);

  useEffect(() => {
    if (!token || !sessionId) {
      setSceneRenderMediaItems([]);
      return;
    }
    void loadSceneRenderMedia();
  }, [loadSceneRenderMedia, sessionId, token]);

  const handleOpenSceneRenderWindow = useCallback(() => {
    setSceneRenderWindowOpen(true);
    if (!token || !sessionId) {
      setSceneRenderError('场景渲染图尚未准备好。');
      return;
    }
    void loadSceneRenderMedia();
  }, [loadSceneRenderMedia, sessionId, token]);

  const previewModelUrl = selectedScheme?.texturedModelUrl ?? baseModel?.modelUrl ?? null;
  const previewUsesRemoteMeshy = Boolean(
    previewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(previewModelUrl),
  );
  const lighting = useMemo(() => LIGHTING_PRESETS[lightPreset], [lightPreset]);
  const lightMultiplier = lightStrength / 100;
  const selectedRecommendation = selectedScheme?.recommendation
    ? RECOMMENDATION_CONFIG[selectedScheme.recommendation]
    : null;
  const hasReviewMetrics = Boolean(selectedScheme?.engineering && selectedScheme?.passenger);
  const refreshPending = Boolean(selectedScheme && refreshingReviewSchemeId === selectedScheme.resultId);
  const showTopRoleReviewSummary = false;

  if (schemes.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-slate-50 p-8 text-center">
        <div className="rounded-2xl bg-slate-100 p-6 text-slate-400">
          <Box size={36} />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-700">暂无评审方案。</p>
        </div>
        {isHost && onRevertToDesign ? (
          <button
            type="button"
            onClick={onRevertToDesign}
            disabled={reverting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
          >
            {reverting ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowLeft size={13} />}
            返回
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 overflow-hidden bg-gradient-to-br from-slate-50 via-slate-50/80 to-blue-50/30">
      <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white/60 backdrop-blur-md">
        <div className="border-b border-slate-200 px-5 py-5">
          <div className="flex flex-col gap-1">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">S3</p>
            <div className="flex items-center gap-2">
              <Layers3 size={16} className="text-slate-400" />
              <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-slate-800">评审</h2>
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {groupedSchemes.map((group) => (
            <section key={group.familyId} className="space-y-2">
              <div className="px-1">
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">分组</p>
                <p className="mt-1 text-xs font-semibold text-slate-700">{group.title}</p>
                <p className="mt-0.5 text-[10px] text-slate-500">
                  {group.schemes.length} 个方案 | {group.memberSummary || '当前工作区'}
                </p>
              </div>
              {group.schemes.map((scheme) => {
                const recommendation = scheme.recommendation ? RECOMMENDATION_CONFIG[scheme.recommendation] : null;
                const isSelected = scheme.id === selectedScheme?.id;
                const isStarred = scheme.starredBy.includes(currentUserId);

                return (
                  <div
                    key={scheme.id}
                    className={`group relative overflow-hidden rounded-2xl border p-3 transition-all duration-300 ${
                      isSelected
                        ? 'border-blue-300 bg-blue-50/50 shadow-sm'
                        : 'border-slate-200 bg-white hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md'
                    }`}
                  >
                    {isSelected && <div className="absolute inset-y-0 left-0 w-1 bg-blue-500" />}
                    <div className="flex items-start justify-between gap-3">
                      <button
                        type="button"
                        onClick={() => setSelectedSchemeId(scheme.id)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className="truncate text-sm font-semibold text-slate-800">{scheme.name}</p>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          {scheme.submittedByName ?? scheme.author}
                        </p>
                      </button>

                      <button
                        type="button"
                        onClick={() => onStarScheme(scheme.resultId)}
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold transition active:scale-90 ${
                          isStarred
                            ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                            : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                        }`}
                        title={isStarred ? '取消收藏' : '收藏该方案'}
                      >
                        <Star size={12} className={isStarred ? 'fill-amber-500 text-amber-500' : ''} />
                        {scheme.starredBy.length}
                      </button>
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        {recommendation ? (
                          <span
                            className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold ${recommendation.bgColor} ${recommendation.color}`}
                          >
                            {recommendation.icon} {recommendation.label}
                          </span>
                        ) : (
                          <span
                            className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold ${reviewStateBadgeClass(scheme.reviewStatus)}`}
                          >
                            {reviewStateLabel(scheme.reviewStatus)}
                          </span>
                        )}
                        {scheme.reviewSettingsStale ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-semibold text-amber-700">
                            已过期
                          </span>
                        ) : null}
                      </div>
                      <span className="text-[11px] font-semibold text-slate-500">
                        {scheme.engineering ? formatCurrency(scheme.engineering.totalCostYuan) : '暂无指标'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        {isHost && onRevertToDesign ? (
          <div className="border-t border-slate-200 p-3">
            {onRevertToDesign ? (
              <button
                type="button"
                onClick={onRevertToDesign}
                disabled={reverting}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
              >
                {reverting ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowLeft size={13} />}
                返回
              </button>
            ) : null}
          </div>
        ) : null}
      </aside>

      {selectedScheme ? (
        <div className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">已选择</p>
              <h3 className="mt-1 text-xl font-bold tracking-tight text-slate-800">{selectedScheme.name}</h3>
              <p className="mt-1 text-xs text-slate-500">
                {selectedGroup?.title ?? selectedScheme.groupTitle} | {selectedScheme.submittedByName ?? selectedScheme.author}
              </p>
              {selectedScheme.reviewSettingsStale ? (
                <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800">
                  评审版本 {selectedScheme.reviewSettingsRevisionUsed ?? '上一版'}。
                </div>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={handleOpenSceneRenderWindow}
                className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
              >
                <Camera size={13} />
                场景渲染图
                <span className="rounded-full bg-white px-1.5 py-0.5 text-[10px] text-blue-600">
                  {sceneRenderImageCount}
                </span>
              </button>
              {onRefreshReview ? (
                <button
                  type="button"
                  onClick={() => onRefreshReview(selectedScheme.resultId)}
                  disabled={refreshPending}
                  className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {refreshPending ? <LoaderCircle size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  刷新
                </button>
              ) : null}
              {selectedRecommendation ? (
                <span
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${selectedRecommendation.bgColor} ${selectedRecommendation.color}`}
                >
                  {selectedRecommendation.icon}
                  {selectedRecommendation.label}
                </span>
              ) : (
                <span
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${reviewStateBadgeClass(selectedScheme.reviewStatus)}`}
                >
                  {reviewStateLabel(selectedScheme.reviewStatus)}
                </span>
              )}
            </div>
          </div>

          {selectedScheme.reviewStatus === 'failed' ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 shadow-sm">
              <p className="font-semibold">评审失败</p>
              <p className="mt-1 text-xs text-rose-700">
                {selectedScheme.reviewErrorMessage || '评审不可用。'}
              </p>
            </div>
          ) : selectedScheme.reviewStatus === 'pending' ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-100 px-4 py-3 text-sm text-slate-700 shadow-sm">
              <p className="font-semibold">评审中</p>
              <p className="mt-1 text-xs text-slate-600">
                正在生成评审。
              </p>
            </div>
          ) : null}

          {hasReviewMetrics && selectedScheme.passenger && selectedScheme.engineering ? (
            <section className="rounded-[2rem] border border-blue-100 bg-gradient-to-br from-blue-50/90 via-white to-slate-50 p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <Star size={15} className="text-blue-600" />
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-600">判断</p>
              </div>
              <p className="mt-3 text-[14px] leading-7 text-slate-700">
                {selectedScheme.overallNarrative ?? selectedScheme.passenger.summary}
              </p>
            </section>
          ) : null}

          {showTopRoleReviewSummary ? (
            <section className="rounded-[2rem] border border-slate-200 bg-white p-5 shadow-sm">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">角色评价</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {selectedScheme.roleReviews.map((roleReview) => {
                  const summary =
                    typeof roleReview.assessment.summary === 'string'
                      ? roleReview.assessment.summary
                      : typeof roleReview.assessment.quick_comment === 'string'
                        ? roleReview.assessment.quick_comment
                        : '该角色已完成评价。';
                  return (
                    <div key={roleReview.roleId} className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-slate-800">{roleReview.roleName}</p>
                        <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold text-slate-500">
                          {roleReview.roleType === 'custom'
                            ? '自定义'
                            : roleReview.roleType === 'engineering'
                              ? '工程类'
                              : '乘客类'}
                        </span>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-slate-600">{summary}</p>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          <div className="space-y-4">
            <div className="min-w-0">
              <div className="relative h-[360px] flex-shrink-0 overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-sm md:h-[420px] xl:h-[500px] 2xl:h-[560px]">
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
                    alt={`${selectedScheme.name} base color texture`}
                    className="h-28 rounded-2xl border border-slate-200 object-contain"
                  />
                ) : null}
              </div>
            ) : previewModelUrl ? (
              <AppErrorBoundary title="阶段三模型预览失败">
                <Suspense
                  fallback={
                    <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                      <LoaderCircle size={16} className="animate-spin" />
                      加载中...
                    </div>
                  }
                >
                  <Canvas
                    className="h-full w-full"
                    shadows={shadowsEnabled}
                    dpr={[1, 1.75]}
                    camera={{ position: [9, 4.5, 9], fov: 42 }}
                  >
                    <color attach="background" args={[lighting.bg]} />
                    <hemisphereLight
                      intensity={lighting.hemisphere * lightMultiplier}
                      color={lighting.hemisphereSky}
                      groundColor={lighting.hemisphereGround}
                    />
                    <ambientLight intensity={lighting.ambient * lightMultiplier} />
                    <directionalLight
                      intensity={lighting.key * lightMultiplier}
                      color={lighting.keyColor}
                      position={lighting.keyPosition}
                      castShadow={shadowsEnabled}
                      shadow-mapSize-width={1536}
                      shadow-mapSize-height={1536}
                      shadow-normalBias={0.02}
                    />
                    <directionalLight
                      intensity={lighting.fill * lightMultiplier}
                      color={lighting.fillColor}
                      position={lighting.fillPosition}
                    />
                    <directionalLight
                      intensity={lighting.rim * lightMultiplier}
                      color={lighting.rimColor}
                      position={lighting.rimPosition}
                    />
                    <spotLight
                      intensity={lighting.spot * lightMultiplier}
                      color={lighting.spotColor}
                      position={lighting.spotPosition}
                      angle={0.5}
                      penumbra={0.7}
                      castShadow={shadowsEnabled}
                    />

                    <ReviewModelScene key={previewModelUrl} modelUrl={previewModelUrl} />
                    <OrbitControls makeDefault enablePan enableZoom enableRotate />
                  </Canvas>
                </Suspense>
              </AppErrorBoundary>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
                <Box size={28} />
                <p className="text-sm font-medium text-slate-500">暂无预览。</p>
              </div>
            )}

            <div className="absolute left-4 top-4 z-20 w-[calc(100%-2rem)] max-w-xs">
              <div className="rounded-2xl border border-slate-200 bg-white/92 text-xs text-slate-700 shadow-sm backdrop-blur">
                <button
                  type="button"
                  onClick={() => setLightingPanelExpanded((current) => !current)}
                  className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left"
                >
                  <div className="flex items-center gap-2 text-slate-600">
                    <Lightbulb size={14} />
                    <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
                      灯光
                    </span>
                  </div>
                  <motion.div animate={{ rotate: lightingPanelExpanded ? 180 : 0 }} transition={{ duration: 0.18 }}>
                    <ChevronDown size={14} className="text-slate-400" />
                  </motion.div>
                </button>

                <AnimatePresence initial={false}>
                  {lightingPanelExpanded ? (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2, ease: 'easeOut' }}
                      className="overflow-hidden border-t border-slate-200"
                    >
                      <div className="p-3">
                        <div className="grid grid-cols-2 gap-1.5">
                          {(Object.keys(LIGHTING_PRESETS) as LightPreset[]).map((preset) => (
                            <button
                              key={preset}
                              type="button"
                              onClick={() => setLightPreset(preset)}
                              className={`rounded-md px-2 py-1 text-[11px] font-semibold capitalize transition ${
                                preset === lightPreset
                                  ? 'bg-blue-600 text-white'
                                  : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100'
                              }`}
                              title={LIGHTING_PRESETS[preset].hint}
                            >
                              {LIGHTING_PRESETS[preset].label}
                            </button>
                          ))}
                        </div>
                        <div className="mt-3">
                          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
                            <span>强度</span>
                            <span>{lightStrength}%</span>
                          </div>
                          <input
                            type="range"
                            min={70}
                            max={140}
                            step={5}
                            value={lightStrength}
                            onChange={(event) => setLightStrength(Number(event.target.value))}
                            className="w-full accent-blue-600"
                          />
                        </div>
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          <button
                            type="button"
                            onClick={() => setShadowsEnabled((current) => !current)}
                            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition ${
                              shadowsEnabled
                                ? 'bg-slate-900 text-white'
                                : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100'
                            }`}
                          >
                            {shadowsEnabled ? '阴影开启' : '阴影关闭'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setLightPreset('daylight');
                              setLightStrength(100);
                              setShadowsEnabled(true);
                            }}
                            className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-100"
                          >
                            重置
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </div>

            {hasReviewMetrics && selectedScheme.engineering && selectedScheme.passenger ? (
              <div
                className={`absolute inset-y-0 right-0 z-20 hidden transition-all duration-300 xl:block ${
                  analysisPanelExpanded ? 'w-[23rem] 2xl:w-[27rem]' : 'w-14'
                }`}
              >
                {analysisPanelExpanded ? (
                  <ReviewPanelContent
                    activeReviewTab={activeReviewTab}
                    onTabChange={setActiveReviewTab}
                    engineering={selectedScheme.engineering}
                    passenger={selectedScheme.passenger}
                    recommendationLabel={selectedRecommendation?.label ?? '等待评审'}
                    passengerLabel={selectedScheme.passengerLabel}
                    engineeringLabel={selectedScheme.engineeringLabel}
                    onToggleCollapse={() => setAnalysisPanelExpanded(false)}
                    className="h-full rounded-none rounded-bl-[2rem] border-0 border-l border-slate-200/80 bg-white/72 backdrop-blur-xl shadow-xl shadow-slate-900/10"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => setAnalysisPanelExpanded(true)}
                    className="flex h-full w-full flex-col items-center justify-center gap-4 border-l border-slate-200/80 bg-white/72 text-slate-600 backdrop-blur-xl transition hover:bg-white/82"
                  >
                    <ArrowLeft size={16} />
                    <span className="[writing-mode:vertical-rl] text-[11px] font-bold uppercase tracking-[0.22em] text-slate-500">
                      分析
                    </span>
                  </button>
                )}
              </div>
            ) : null}
              </div>
            </div>

          {hasReviewMetrics && selectedScheme.engineering && selectedScheme.passenger ? (
            <div className="xl:hidden">
              <ReviewPanelContent
                activeReviewTab={activeReviewTab}
                onTabChange={setActiveReviewTab}
                engineering={selectedScheme.engineering}
                passenger={selectedScheme.passenger}
                recommendationLabel={selectedRecommendation?.label ?? '等待评审'}
                passengerLabel={selectedScheme.passengerLabel}
                engineeringLabel={selectedScheme.engineeringLabel}
              />
            </div>
          ) : (
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <AlertCircle size={16} className="text-slate-500" />
                <h4 className="text-sm font-semibold text-slate-800">评审不可用</h4>
              </div>
            </section>
          )}
        </div>
      </div>
      ) : null}
      {sceneRenderWindowOpen ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 p-6 backdrop-blur-sm">
          <div className="flex max-h-[86vh] w-full max-w-6xl flex-col overflow-hidden rounded-[2rem] border border-white/20 bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-blue-600">场景渲染图</p>
                <h3 className="mt-1 text-xl font-bold tracking-tight text-slate-800">按方案查看已生成图片</h3>
                <p className="mt-1 text-sm text-slate-500">这里会显示阶段二和阶段四保存到当前会议的渲染图。</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void loadSceneRenderMedia();
                  }}
                  disabled={sceneRenderLoading}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                >
                  {sceneRenderLoading ? <LoaderCircle size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  刷新
                </button>
                <button
                  type="button"
                  onClick={() => setSceneRenderWindowOpen(false)}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
                  aria-label="关闭场景渲染图窗口"
                >
                  <X size={15} />
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-6">
              {sceneRenderError ? (
                <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {sceneRenderError}
                </div>
              ) : null}
              {sceneRenderLoading && sceneRenderImageCount === 0 ? (
                <div className="flex h-48 items-center justify-center gap-2 rounded-3xl border border-dashed border-slate-200 bg-white text-sm text-slate-500">
                  <LoaderCircle size={16} className="animate-spin" />
                  加载场景渲染图...
                </div>
              ) : sceneRenderImageCount > 0 ? (
                <div className="space-y-5">
                  {groupedSchemes.map((group) => {
                    const groupImageCount = group.schemes.reduce(
                      (total, scheme) => total + (sceneRenderImagesByResultId.get(scheme.resultId)?.length ?? 0),
                      0,
                    );
                    if (groupImageCount === 0) {
                      return null;
                    }
                    return (
                      <section key={`render-group-${group.familyId}`} className="rounded-[1.5rem] border border-slate-200 bg-white p-4 shadow-sm">
                        <div className="mb-4 flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-slate-800">{group.title}</p>
                            <p className="mt-1 text-xs text-slate-500">{group.memberSummary || '当前工作区'} | {groupImageCount} 张</p>
                          </div>
                          <ImageIcon size={16} className="text-blue-500" />
                        </div>
                        <div className="space-y-4">
                          {group.schemes.map((scheme) => {
                            const images = sceneRenderImagesByResultId.get(scheme.resultId) ?? [];
                            if (images.length === 0) {
                              return null;
                            }
                            return (
                              <div key={`render-scheme-${scheme.resultId}`}>
                                <div className="mb-2 flex items-center justify-between gap-3">
                                  <p className="truncate text-xs font-semibold text-slate-700">{scheme.name}</p>
                                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-500">
                                    {images.length} 张
                                  </span>
                                </div>
                                <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
                                  {images.map((item) => (
                                    <button
                                      key={item.id}
                                      type="button"
                                      onClick={() => setSceneRenderLightboxItem(item)}
                                      className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 text-left transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
                                    >
                                      <img src={item.mediaUrl} alt={`${scheme.name} 场景渲染图`} className="aspect-video w-full object-cover" />
                                      <span className="absolute right-2 top-2 rounded-full bg-black/55 p-1 text-white opacity-0 transition group-hover:opacity-100">
                                        <Maximize2 size={12} />
                                      </span>
                                      <div className="px-3 py-2">
                                        <p className="truncate text-[11px] font-semibold text-slate-600">{item.schemeName || scheme.name}</p>
                                        <p className="mt-0.5 text-[10px] text-slate-400">
                                          {new Date(item.createdAt).toLocaleString('zh-CN')}
                                        </p>
                                      </div>
                                    </button>
                                  ))}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    );
                  })}
                </div>
              ) : (
                <div className="flex h-56 flex-col items-center justify-center gap-3 rounded-3xl border border-dashed border-slate-200 bg-white text-center">
                  <div className="rounded-2xl bg-slate-100 p-4 text-slate-400">
                    <ImageIcon size={24} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-700">暂无渲染图</p>
                    <p className="mt-1 text-xs text-slate-500">在阶段二共享预览或阶段四生成后，会自动出现在这里。</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
      {sceneRenderLightboxItem ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/82 p-6 backdrop-blur-sm">
          <div className="relative max-h-full w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-slate-950 shadow-2xl">
            <button
              type="button"
              onClick={() => setSceneRenderLightboxItem(null)}
              className="absolute right-4 top-4 z-10 inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-slate-700 shadow-sm transition hover:bg-white"
              aria-label="关闭场景渲染图预览"
            >
              <X size={16} />
            </button>
            <img src={sceneRenderLightboxItem.mediaUrl} alt="放大的场景渲染图" className="max-h-[78vh] w-full object-contain" />
            <div className="flex items-start gap-2 border-t border-white/10 bg-slate-950 px-5 py-3 text-xs leading-5 text-white/70">
              <ImageIcon size={14} className="mt-0.5 shrink-0" />
              <span>{sceneRenderLightboxItem.prompt}</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
    <p className="mt-1 text-sm font-semibold text-slate-800">{value}</p>
  </div>
);

const ReviewPanelContent: React.FC<{
  activeReviewTab: ReviewTab;
  onTabChange: (tab: ReviewTab) => void;
  engineering: NonNullable<ReviewScheme['engineering']>;
  passenger: NonNullable<ReviewScheme['passenger']>;
  recommendationLabel: string;
  passengerLabel: string;
  engineeringLabel: string;
  onToggleCollapse?: () => void;
  className?: string;
}> = ({
  activeReviewTab,
  onTabChange,
  engineering,
  passenger,
  recommendationLabel,
  passengerLabel,
  engineeringLabel,
  onToggleCollapse,
  className = '',
}) => (
  <section className={`min-w-0 rounded-[2rem] border border-slate-200/80 bg-white/78 p-4 shadow-sm backdrop-blur-xl flex h-full flex-col overflow-hidden ${className}`}>
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">评审</p>
      </div>
      {onToggleCollapse ? (
        <button
          type="button"
          onClick={onToggleCollapse}
          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          title="收起分析面板"
        >
          <ArrowRight size={14} />
        </button>
      ) : null}
    </div>

    <div className="mt-4 grid grid-cols-2 rounded-2xl bg-slate-100 p-1">
      <button
        type="button"
        onClick={() => onTabChange('passenger')}
        className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-bold uppercase tracking-wider transition ${
          activeReviewTab === 'passenger'
            ? 'bg-white text-indigo-600 shadow-sm'
            : 'text-slate-500 hover:text-slate-800'
        }`}
      >
        <Users size={14} />
        <span className="truncate">{passengerLabel}</span>
      </button>
      <button
        type="button"
        onClick={() => onTabChange('engineering')}
        className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-bold uppercase tracking-wider transition ${
          activeReviewTab === 'engineering'
            ? 'bg-white text-slate-800 shadow-sm'
            : 'text-slate-500 hover:text-slate-800'
        }`}
      >
        <HardHat size={14} />
        <span className="truncate">{engineeringLabel}</span>
      </button>
    </div>

    <div className="mt-4 flex-1 overflow-y-auto pr-1">
      <AnimatePresence mode="wait" initial={false}>
        {activeReviewTab === 'passenger' ? (
          <motion.div
            key="passenger-tab"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="space-y-4"
          >
            <div className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4">
              <div className="flex flex-col gap-4 min-[440px]:flex-row min-[440px]:items-start min-[440px]:justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-500">总体评价</p>
                  <p className="mt-2 break-words text-[13px] font-medium leading-[1.6] text-slate-700">{passenger.summary}</p>
                </div>
                <div className="shrink-0 rounded-2xl bg-white px-4 py-3 text-center shadow-sm ring-1 ring-slate-900/5 min-[440px]:w-24">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">分数</p>
                  <p className="mt-1 text-3xl font-extrabold tracking-tighter text-blue-900">{passenger.overallScore.toFixed(1)}</p>
                  <p className="text-[10px] font-bold text-slate-400">/ 10</p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">指标</p>
              <div className="mt-4 flex justify-center">
                <RadarChart
                  size={220}
                  data={[
                    { label: '第一印象', value: passenger.scores.firstImpression, full: 10 },
                    { label: '安全信任', value: passenger.scores.safetyTrust, full: 10 },
                    { label: '舒适整洁', value: passenger.scores.comfortCleanliness, full: 10 },
                    { label: '品质感', value: passenger.scores.perceivedQuality, full: 10 },
                    { label: '速度感', value: passenger.scores.speedMotion, full: 10 },
                    { label: '情感性格', value: passenger.scores.emotionCharacter, full: 10 },
                  ]}
                />
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <PassengerScoreCompact
                  label="第一印象"
                  value={passenger.scores.firstImpression}
                  hint="是否吸引人、易记、现代并具有科技感"
                />
                <PassengerScoreCompact
                  label="安全信任"
                  value={passenger.scores.safetyTrust}
                  hint="是否显得安全、可靠、安心且值得信任"
                />
                <PassengerScoreCompact
                  label="舒适整洁"
                  value={passenger.scores.comfortCleanliness}
                  hint="是否干净、整洁、放松且视觉统一"
                />
                <PassengerScoreCompact
                  label="品质感"
                  value={passenger.scores.perceivedQuality}
                  hint="是否具有高级感，而不是廉价、塑料感、过亮或暗沉"
                />
                <PassengerScoreCompact
                  label="速度感"
                  value={passenger.scores.speedMotion}
                  hint="是否显得快速、流线，并具有方向性的动势"
                />
                <PassengerScoreCompact
                  label="情感性格"
                  value={passenger.scores.emotionCharacter}
                  hint="是否生动、有辨识度，并能产生情感连接"
                />
              </div>
            </div>

            <PassengerInsightList
              title="优点"
              emptyText="暂无乘客视角优点。"
              items={passenger.strengths}
              toneClass="border-emerald-200 bg-emerald-50/50"
              titleClass="text-emerald-700"
              badgeClass="bg-emerald-600 text-white"
              itemClass="border-emerald-100 bg-white/85 text-emerald-950 shadow-sm"
            />
            <PassengerInsightList
              title="问题"
              emptyText="暂无乘客视角问题。"
              items={passenger.issues}
              toneClass="border-rose-200 bg-rose-50/50"
              titleClass="text-rose-700"
              badgeClass="bg-rose-600 text-white"
              itemClass="border-rose-100 bg-white/85 text-rose-950 shadow-sm"
            />
            <PassengerInsightList
              title="建议"
              emptyText="暂无乘客视角建议。"
              items={passenger.suggestions}
              toneClass="border-blue-200 bg-blue-50/50"
              titleClass="text-blue-700"
              badgeClass="bg-blue-600 text-white"
              itemClass="border-blue-100 bg-white/85 text-blue-900 shadow-sm"
            />
          </motion.div>
        ) : (
          <motion.div
            key="engineering-tab"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="space-y-4"
          >
            <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-5">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">工程概览</p>
              {engineering.summary ? (
                <p className="mt-3 text-[13px] leading-[1.65] text-slate-700">{engineering.summary}</p>
              ) : null}
              <div className="mt-3">
                <p className="text-3xl font-extrabold tracking-tighter text-blue-900">{formatCurrency(engineering.totalCostYuan)}</p>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2">
                <MetricCard label="材料成本" value={formatCurrency(engineering.materialCostYuan)} />
                <MetricCard label="人工成本" value={formatCurrency(engineering.laborCostYuan)} />
                <MetricCard label="工时" value={`${engineering.laborHours} h`} />
                <MetricCard label="油漆用量" value={`${engineering.paintVolumeKg.toFixed(1)} kg`} />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${riskBadgeClass(engineering.colorVarianceRisk)}`}
                >
                  风险 {engineering.colorVarianceRisk}
                </span>
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${durabilityBadgeClass(engineering.weatherDurability)}`}
                >
                  耐久 {engineering.weatherDurability}
                </span>
                <span className="inline-flex items-center rounded-full bg-slate-200 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                  维护周期 {engineering.maintenanceCycleYears} 年
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <MetricCard label="色区数量" value={String(engineering.colorZoneCount)} />
              <MetricCard label="渐变面积" value={`${engineering.gradientRatioPercent.toFixed(1)}%`} />
              <MetricCard label="遮蔽步骤" value={String(engineering.maskingSteps)} />
              <MetricCard label="工艺步骤" value={String(engineering.processSteps)} />
              <MetricCard label="曲面贴合" value={`${engineering.curveConformanceScore}/100`} />
              <MetricCard label="建议" value={recommendationLabel} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  </section>
);

const PassengerScoreCompact: React.FC<{ label: string; value: number; hint: string }> = ({
  label,
  value,
  hint,
}) => {
  const [hintVisible, setHintVisible] = useState(false);
  const tooltipId = `passenger-compact-hint-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;

  return (
    <div className="group relative rounded-xl border border-slate-100 bg-white p-2.5 transition-all hover:border-blue-200 hover:shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="truncate text-[10px] font-bold uppercase tracking-wider text-slate-400 group-hover:text-slate-600">{label}</p>
            <button
              type="button"
              onMouseEnter={() => setHintVisible(true)}
              onMouseLeave={() => setHintVisible(false)}
              className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-slate-200 bg-white text-[9px] font-bold text-slate-400 transition hover:border-blue-300 hover:text-blue-500"
            >
              ?
            </button>
          </div>
          <p className="mt-0.5 text-sm font-bold text-slate-700">{value.toFixed(1)}</p>
        </div>
        <div className={`h-1.5 w-1.5 rounded-full ${value >= 8 ? 'bg-emerald-500' : value >= 6 ? 'bg-blue-500' : 'bg-amber-500'}`} />
      </div>
      <AnimatePresence>
        {hintVisible && (
          <motion.div
            id={tooltipId}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className="absolute left-0 right-0 top-full z-30 mt-1 rounded-lg border border-slate-200 bg-white/98 p-2 text-[10px] leading-relaxed text-slate-600 shadow-xl backdrop-blur-sm"
          >
            {hint}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const RadarChart: React.FC<{
  data: { label: string; value: number; full: number }[];
  size?: number;
}> = ({ data, size = 280 }) => {
  const center = size / 2;
  const radius = (size / 2) * 0.62;
  const angleStep = (Math.PI * 2) / data.length;

  const points = data.map((d, i) => {
    const angle = i * angleStep - Math.PI / 2;
    const x = center + radius * (d.value / d.full) * Math.cos(angle);
    const y = center + radius * (d.value / d.full) * Math.sin(angle);
    return { x, y };
  });

  const polygonPath = points.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <div className="relative flex items-center justify-center py-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="overflow-visible">
        {/* Outer Circle Ring */}
        <circle cx={center} cy={center} r={radius} fill="none" stroke="#f1f5f9" strokeWidth="1" />
        
        {/* Grids */}
        {[0.25, 0.5, 0.75].map((factor) => (
          <polygon
            key={factor}
            points={data
              .map((_, i) => {
                const angle = i * angleStep - Math.PI / 2;
                const rx = center + radius * factor * Math.cos(angle);
                const ry = center + radius * factor * Math.sin(angle);
                return `${rx},${ry}`;
              })
              .join(' ')}
            fill="none"
            stroke="#f1f5f9"
            strokeWidth="1"
          />
        ))}

        {/* Axis */}
        {data.map((_, i) => {
          const angle = i * angleStep - Math.PI / 2;
          return (
            <line
              key={i}
              x1={center}
              y1={center}
              x2={center + radius * Math.cos(angle)}
              y2={center + radius * Math.sin(angle)}
              stroke="#f1f5f9"
              strokeWidth="1"
            />
          );
        })}

        {/* Data area */}
        <motion.polygon
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 0.15, scale: 1 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          points={polygonPath}
          fill="#4f46e5"
        />
        <motion.polygon
          initial={{ pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: 1.2, ease: 'easeInOut' }}
          points={polygonPath}
          fill="none"
          stroke="#4f46e5"
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* Data Points */}
        {points.map((p, i) => (
          <motion.circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={3}
            fill="white"
            stroke="#4f46e5"
            strokeWidth="2"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.8 + i * 0.05 }}
          />
        ))}

        {/* Labels */}
        {data.map((d, i) => {
          const angle = i * angleStep - Math.PI / 2;
          const labelRadius = radius + 25;
          const lx = center + labelRadius * Math.cos(angle);
          const ly = center + labelRadius * Math.sin(angle);
          
          let anchor = 'middle';
          if (Math.cos(angle) > 0.1) anchor = 'start';
          if (Math.cos(angle) < -0.1) anchor = 'end';

          return (
            <g key={i}>
              <text
                x={lx}
                y={ly}
                textAnchor={anchor as "end" | "middle" | "start"}
                className="text-[10px] font-bold uppercase tracking-tight fill-slate-400 group-hover:fill-slate-600 transition-colors"
                dominantBaseline="middle"
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const PassengerInsightList: React.FC<{
  title: string;
  items: string[];
  emptyText: string;
  toneClass: string;
  titleClass: string;
  badgeClass: string;
  itemClass: string;
}> = ({ title, items, emptyText, toneClass, titleClass, badgeClass, itemClass }) => (
  <div className={`rounded-2xl border p-3.5 ${toneClass}`}>
    <p className={`text-[10px] font-semibold uppercase tracking-wider ${titleClass}`}>{title}</p>
    {items.length > 0 ? (
      <div className="mt-3 space-y-2">
        {items.map((item, index) => (
          <div
            key={`${title}-${index}`}
            className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 text-[13px] leading-5 ${itemClass}`}
          >
            <span
              className={`mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${badgeClass}`}
            >
              {index + 1}
            </span>
            <p className="min-w-0 flex-1">{item}</p>
          </div>
        ))}
      </div>
    ) : (
      <p className="mt-3 text-sm text-slate-500">{emptyText}</p>
    )}
  </div>
);

export default Stage3ReviewView;
