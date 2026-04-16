import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Box,
  Layers3,
  LoaderCircle,
  Star,
  Train,
  Wrench,
} from 'lucide-react';
import type { BaseModelMeta, ReviewScheme } from '../../types/design.ts';
import { RECOMMENDATION_CONFIG } from '../../utils/reviewScoring.ts';
import AppErrorBoundary from '../AppErrorBoundary.tsx';

interface Stage3ReviewViewProps {
  schemes: ReviewScheme[];
  baseModel: BaseModelMeta | null;
  isHost: boolean;
  currentUserId: string;
  onStarScheme: (schemeId: string) => void;
  onRevertToDesign?: () => void;
  onAdvanceToPreview?: () => void;
  reverting?: boolean;
  advancing?: boolean;
}

const ReviewModelScene: React.FC<{ modelUrl: string }> = ({ modelUrl }) => {
  const { scene } = useGLTF(modelUrl);
  const cloned = useMemo(() => scene.clone(true), [scene]);
  return (
    <Bounds fit clip observe margin={1.15}>
      <primitive object={cloned} />
    </Bounds>
  );
};

const formatCurrency = (value: number): string => `CNY ${Math.round(value).toLocaleString('zh-CN')}`;

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

const passengerBarClass = (value: number): string => {
  if (value >= 80) return 'bg-emerald-500';
  if (value >= 65) return 'bg-blue-500';
  if (value >= 50) return 'bg-amber-500';
  return 'bg-rose-500';
};

const Stage3ReviewView: React.FC<Stage3ReviewViewProps> = ({
  schemes,
  baseModel,
  isHost,
  currentUserId,
  onStarScheme,
  onRevertToDesign,
  onAdvanceToPreview,
  reverting = false,
  advancing = false,
}) => {
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>(schemes[0]?.id ?? '');

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

  const previewModelUrl = selectedScheme?.texturedModelUrl ?? baseModel?.modelUrl ?? null;
  const previewUsesRemoteMeshy = Boolean(
    previewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(previewModelUrl),
  );
  const selectedRecommendation = selectedScheme
    ? RECOMMENDATION_CONFIG[selectedScheme.recommendation]
    : null;

  if (schemes.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-slate-50 p-8 text-center">
        <div className="rounded-2xl bg-slate-100 p-6 text-slate-400">
          <Box size={36} />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-700">No review schemes are ready yet.</p>
          <p className="mt-1 text-xs text-slate-500">
            Generate textured model results in Stage 2 before entering scheme review.
          </p>
        </div>
        {isHost && onRevertToDesign ? (
          <button
            type="button"
            onClick={onRevertToDesign}
            disabled={reverting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50"
          >
            {reverting ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowLeft size={13} />}
            Back To Stage 2
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-slate-50">
      <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-4">
          <div className="flex items-center gap-2">
            <Layers3 size={16} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-slate-800">Stage 3 Review</h2>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">
            {schemes.length} textured scheme{schemes.length > 1 ? 's' : ''} ready for comparison
          </p>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {schemes.map((scheme) => {
            const recommendation = RECOMMENDATION_CONFIG[scheme.recommendation];
            const isSelected = scheme.id === selectedScheme?.id;
            const isStarred = scheme.starredBy.includes(currentUserId);

            return (
              <div
                key={scheme.id}
                className={`rounded-2xl border p-3 transition ${
                  isSelected
                    ? 'border-blue-400 bg-blue-50 shadow-sm ring-2 ring-blue-500/15'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => setSelectedSchemeId(scheme.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-semibold text-slate-800">{scheme.name}</p>
                    <p className="mt-0.5 text-[11px] text-slate-500">{scheme.author}</p>
                  </button>

                  <button
                    type="button"
                    onClick={() => onStarScheme(scheme.schemeId)}
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold transition ${
                      isStarred
                        ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                        : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                    }`}
                    title={isStarred ? 'Remove your star' : 'Star this scheme'}
                  >
                    <Star size={12} className={isStarred ? 'fill-amber-500 text-amber-500' : ''} />
                    {scheme.starredBy.length}
                  </button>
                </div>

                <div className="mt-3 flex items-center justify-between gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold ${recommendation.bgColor} ${recommendation.color}`}
                  >
                    {recommendation.icon} {recommendation.label}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {formatCurrency(scheme.engineering.totalCostYuan)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {isHost ? (
          <div className="space-y-2 border-t border-slate-200 p-3">
            {onRevertToDesign ? (
              <button
                type="button"
                onClick={onRevertToDesign}
                disabled={reverting}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
              >
                {reverting ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowLeft size={13} />}
                Back To Stage 2
              </button>
            ) : null}
            {onAdvanceToPreview ? (
              <button
                type="button"
                onClick={onAdvanceToPreview}
                disabled={advancing}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
              >
                {advancing ? <LoaderCircle size={13} className="animate-spin" /> : <ArrowRight size={13} />}
                Enter Stage 4
              </button>
            ) : null}
          </div>
        ) : null}
      </aside>

      {selectedScheme ? (
        <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Selected Scheme</p>
              <h3 className="mt-1 text-xl font-semibold text-slate-900">{selectedScheme.name}</h3>
              <p className="mt-1 text-sm text-slate-500">
                Review the generated 3D result, engineering feasibility, and passenger experience together.
              </p>
            </div>
            {selectedRecommendation ? (
              <span
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${selectedRecommendation.bgColor} ${selectedRecommendation.color}`}
              >
                {selectedRecommendation.icon}
                {selectedRecommendation.label}
              </span>
            ) : null}
          </div>

          <div className="relative h-80 shrink-0 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
            {previewUsesRemoteMeshy ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
                <div className="rounded-2xl bg-amber-50 p-4 text-amber-500">
                  <AlertCircle size={24} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-700">Remote Meshy preview is not embedded here.</p>
                  <p className="mt-1 text-xs text-slate-500">
                    This scheme still carries its review data. Open the model from Stage 2 if you want the remote preview.
                  </p>
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
              <AppErrorBoundary title="Stage 3 model preview failed">
                <Suspense
                  fallback={
                    <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                      <LoaderCircle size={16} className="animate-spin" />
                      Loading 3D preview...
                    </div>
                  }
                >
                  <Canvas camera={{ position: [9, 4.5, 9], fov: 42 }}>
                    <color attach="background" args={['#f8fafc']} />
                    <ambientLight intensity={0.9} />
                    <directionalLight intensity={1.2} position={[6, 8, 6]} />
                    <directionalLight intensity={0.45} position={[-6, 5, -4]} />
                    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.1, 0]} receiveShadow>
                      <planeGeometry args={[32, 32]} />
                      <meshStandardMaterial color="#e2e8f0" />
                    </mesh>
                    <ReviewModelScene key={previewModelUrl} modelUrl={previewModelUrl} />
                    <OrbitControls makeDefault enablePan enableZoom enableRotate />
                  </Canvas>
                </Suspense>
              </AppErrorBoundary>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-400">
                <Box size={28} />
                <p className="text-sm font-medium text-slate-500">No preview model available.</p>
              </div>
            )}

            <div className="absolute left-4 top-4 rounded-2xl border border-slate-200 bg-white/92 px-3 py-2 text-xs text-slate-700 shadow-sm backdrop-blur">
              <p className="font-semibold text-slate-800">Session Base Model</p>
              <p>base_model_id: {baseModel?.baseModelId ?? 'N/A'}</p>
              <p>precision: {baseModel?.precisionLevel ?? 'unknown'}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <Wrench size={16} className="text-blue-600" />
                <h4 className="text-sm font-semibold text-slate-800">Engineering Perspective</h4>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-700">
                <MetricCard label="Paint Volume" value={`${selectedScheme.engineering.paintVolumeKg.toFixed(1)} kg`} />
                <MetricCard label="Color Zones" value={String(selectedScheme.engineering.colorZoneCount)} />
                <MetricCard label="Masking Steps" value={String(selectedScheme.engineering.maskingSteps)} />
                <MetricCard
                  label="Gradient Area"
                  value={`${selectedScheme.engineering.gradientRatioPercent.toFixed(1)}%`}
                />
                <MetricCard label="Labor Hours" value={`${selectedScheme.engineering.laborHours} h`} />
                <MetricCard label="Process Steps" value={String(selectedScheme.engineering.processSteps)} />
                <MetricCard
                  label="Curve Fit Difficulty"
                  value={`${selectedScheme.engineering.curveConformanceScore}/100`}
                />
                <MetricCard label="Material Cost" value={formatCurrency(selectedScheme.engineering.materialCostYuan)} />
                <MetricCard label="Labor Cost" value={formatCurrency(selectedScheme.engineering.laborCostYuan)} />
                <MetricCard label="Total Cost" value={formatCurrency(selectedScheme.engineering.totalCostYuan)} />
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${riskBadgeClass(selectedScheme.engineering.colorVarianceRisk)}`}
                >
                  Risk {selectedScheme.engineering.colorVarianceRisk}
                </span>
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${durabilityBadgeClass(selectedScheme.engineering.weatherDurability)}`}
                >
                  Durability {selectedScheme.engineering.weatherDurability}
                </span>
                <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                  Maintenance {selectedScheme.engineering.maintenanceCycleYears} years
                </span>
              </div>
            </section>

            <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <Train size={16} className="text-indigo-600" />
                <h4 className="text-sm font-semibold text-slate-800">Passenger Perspective</h4>
              </div>
              <div className="mt-4 space-y-3">
                <PassengerMetric label="Ride Comfort" value={selectedScheme.passenger.rideComfort} />
                <PassengerMetric label="Platform Recognition" value={selectedScheme.passenger.platformRecognition} />
                <PassengerMetric label="Social Appeal" value={selectedScheme.passenger.socialAppeal} />
                <PassengerMetric label="Cultural Fit" value={selectedScheme.passenger.culturalFit} />
                <PassengerMetric label="First Impression" value={selectedScheme.passenger.firstImpression} />
              </div>
            </section>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Recommendation</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">
                {selectedRecommendation?.label ?? 'Awaiting review'}
              </p>
            </div>

            <button
              type="button"
              onClick={() => onStarScheme(selectedScheme.schemeId)}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition ${
                selectedScheme.starredBy.includes(currentUserId)
                  ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              <Star
                size={16}
                className={selectedScheme.starredBy.includes(currentUserId) ? 'fill-amber-500 text-amber-500' : ''}
              />
              {selectedScheme.starredBy.includes(currentUserId) ? 'Starred' : 'Star This Scheme'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-2xl bg-slate-50 px-3 py-2">
    <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</p>
    <p className="mt-1 text-sm font-semibold text-slate-800">{value}</p>
  </div>
);

const PassengerMetric: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <div>
    <div className="mb-1 flex items-center justify-between text-sm">
      <span className="text-slate-600">{label}</span>
      <span className="font-semibold text-slate-800">{value}</span>
    </div>
    <div className="h-2 overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full transition-all ${passengerBarClass(value)}`} style={{ width: `${value}%` }} />
    </div>
  </div>
);

export default Stage3ReviewView;
