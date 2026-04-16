import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { AlertCircle, Camera, Download, Lightbulb, LoaderCircle, PackageOpen } from 'lucide-react';
import type { BaseModelMeta, ReviewScheme } from '../../types/design.ts';
import { RECOMMENDATION_CONFIG } from '../../utils/reviewScoring.ts';

interface Stage4PreviewViewProps {
  schemes: ReviewScheme[];
  baseModel: BaseModelMeta | null;
}

type LightPreset = 'daylight' | 'cloudy' | 'platform' | 'studio';

const PRECISION_LABEL_MAP = {
  authoritative: 'Authoritative',
  standard: 'Standard',
  approximate: 'Approximate',
} as const;

const SOURCE_LABEL_MAP = {
  upload: 'Uploaded',
  library: 'Library',
  generate: 'Generated',
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

const formatCurrency = (value: number): string => `CNY ${Math.round(value).toLocaleString('zh-CN')}`;

const Stage4PreviewView: React.FC<Stage4PreviewViewProps> = ({ schemes, baseModel }) => {
  const [selectedSchemeId, setSelectedSchemeId] = useState<string>(schemes[0]?.id ?? '');
  const [lightPreset, setLightPreset] = useState<LightPreset>('daylight');

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
  const recommendation = selectedScheme ? RECOMMENDATION_CONFIG[selectedScheme.recommendation] : null;

  if (!baseModel || !selectedScheme) {
    return (
      <div className="flex flex-1 items-center justify-center bg-slate-50 text-slate-500">
        Complete Stage 2 review selection before entering Stage 4 preview.
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 overflow-hidden bg-slate-50">
      <div className="flex-1 p-4">
        <div className="relative h-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
          {previewUsesRemoteMeshy ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
              <div className="rounded-2xl bg-amber-50 p-4 text-amber-500">
                <AlertCircle size={24} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">Remote Meshy preview is not embedded here.</p>
                <p className="mt-1 text-xs text-slate-500">
                  You can still compare this candidate and export its metadata from the right panel.
                </p>
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
                  Loading 3D preview...
                </div>
              }
            >
              <Canvas shadows camera={{ position: [9, 4, 9], fov: 42 }}>
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
              No preview model available.
            </div>
          )}

          <div className="absolute left-4 top-4 rounded-xl border border-slate-200 bg-white/90 p-3 text-xs text-slate-700 shadow-sm backdrop-blur">
            <p className="font-semibold text-slate-800">Session Base Model</p>
            <p>base_model_id: {baseModel.baseModelId}</p>
            <p>source: {SOURCE_LABEL_MAP[baseModel.sourceType]}</p>
            <p>precision: {PRECISION_LABEL_MAP[baseModel.precisionLevel]}</p>
          </div>

          <div className="absolute right-4 top-4 rounded-xl border border-slate-200 bg-white/90 p-3 text-xs text-slate-700 shadow-sm backdrop-blur">
            <div className="mb-2 flex items-center gap-1 text-slate-600">
              <Lightbulb size={14} />
              Light Preset
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
                  {preset}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <aside className="z-20 flex w-96 flex-col border-l border-slate-200 bg-white p-4">
        <h3 className="mb-1 text-sm font-semibold text-slate-800">Stage 4 Preview</h3>
        <p className="mb-4 text-xs text-slate-500">Compare the reviewed candidates and prepare exports.</p>

        <div className="mb-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Design Candidates</p>
          {schemes.map((scheme) => {
            const schemeRecommendation = RECOMMENDATION_CONFIG[scheme.recommendation];
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
                    <p className="mt-1 text-xs text-slate-500">{formatCurrency(scheme.engineering.totalCostYuan)}</p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold ${schemeRecommendation.bgColor} ${schemeRecommendation.color}`}
                  >
                    {schemeRecommendation.label}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <p className="mb-1 font-semibold text-slate-800">Engineering Summary</p>
          <p>Paint: {selectedScheme.engineering.paintVolumeKg.toFixed(1)} kg</p>
          <p>Total Cost: {formatCurrency(selectedScheme.engineering.totalCostYuan)}</p>
          <p>Labor: {selectedScheme.engineering.laborHours} h</p>
          <p>Risk: {selectedScheme.engineering.colorVarianceRisk}</p>
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Passenger Summary</p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-700">
            <PreviewMetric label="Comfort" value={selectedScheme.passenger.rideComfort} />
            <PreviewMetric label="Recognition" value={selectedScheme.passenger.platformRecognition} />
            <PreviewMetric label="Appeal" value={selectedScheme.passenger.socialAppeal} />
            <PreviewMetric label="Impression" value={selectedScheme.passenger.firstImpression} />
          </div>
        </div>

        <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <p className="font-semibold text-slate-800">Recommendation</p>
          <p className="mt-1">{recommendation?.label ?? 'Awaiting recommendation'}</p>
          <p className="mt-1 text-xs text-slate-500">{selectedScheme.starredBy.length} member star(s)</p>
        </div>

        <div className="mt-auto space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Export</p>
          <ActionButton label="Export UV Layout (PNG)" icon={<Download size={14} />} />
          <ActionButton label="Export Engineering Report (PDF)" icon={<Download size={14} />} />
          <ActionButton label="Export 3D Screenshot" icon={<Camera size={14} />} />

          {baseModel.exportGlbAllowed ? (
            <ActionButton label="Export Textured GLB" icon={<PackageOpen size={14} />} />
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
              Current model license restricts GLB export. Use preview package export instead.
            </div>
          )}

          {!baseModel.exportGlbAllowed ? (
            <ActionButton label="Export Preview Package" icon={<PackageOpen size={14} />} />
          ) : null}
        </div>
      </aside>
    </div>
  );
};

const PreviewMetric: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <div className="rounded-xl bg-slate-50 px-3 py-2">
    <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</p>
    <p className="mt-1 font-semibold text-slate-800">{value}</p>
  </div>
);

const ActionButton: React.FC<{ label: string; icon: React.ReactNode }> = ({ label, icon }) => (
  <button
    type="button"
    className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
  >
    {icon}
    {label}
  </button>
);

export default Stage4PreviewView;
