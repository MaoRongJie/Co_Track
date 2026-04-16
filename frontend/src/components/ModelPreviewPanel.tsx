import React, { Suspense, useMemo } from 'react';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import { Box, LoaderCircle } from 'lucide-react';

interface ModelPreviewPanelProps {
  modelUrl: string | null;
  title?: string;
  subtitle?: string | null;
  loading?: boolean;
}

const PreviewModel: React.FC<{ modelUrl: string }> = ({ modelUrl }) => {
  const { scene } = useGLTF(modelUrl);
  const clonedScene = useMemo(() => scene.clone(true), [scene]);

  return (
    <Bounds fit clip observe margin={1.15}>
      <primitive object={clonedScene} />
    </Bounds>
  );
};

const PreviewEmptyState: React.FC<{ title: string; subtitle: string }> = ({ title, subtitle }) => (
  <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
    <div className="rounded-2xl bg-slate-100 p-4 text-slate-500">
      <Box size={28} />
    </div>
    <div>
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
    </div>
  </div>
);

const ModelPreviewPanel: React.FC<ModelPreviewPanelProps> = ({
  modelUrl,
  title = 'Base Model Preview',
  subtitle,
  loading = false,
}) => {
  const fallbackSubtitle =
    subtitle ?? (loading ? 'The uploaded model is being processed and prepared for UV work.' : 'Choose a GLB/GLTF model to preview it here.');

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{fallbackSubtitle}</p>
        </div>
        {loading ? (
          <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
            <LoaderCircle size={13} className="animate-spin" />
            Processing
          </span>
        ) : null}
      </div>

      <div className="relative h-80 bg-gradient-to-br from-slate-100 via-white to-blue-50">
        {!modelUrl ? (
          <PreviewEmptyState title="Preview will appear here" subtitle={fallbackSubtitle} />
        ) : (
          <Suspense fallback={<PreviewEmptyState title="Loading 3D preview" subtitle="Rendering the uploaded model in the browser." />}>
            <Canvas camera={{ position: [3.6, 2.2, 4.6], fov: 42 }}>
              <color attach="background" args={['#f8fafc']} />
              <ambientLight intensity={0.95} />
              <directionalLight intensity={1.15} position={[4, 7, 5]} />
              <directionalLight intensity={0.45} position={[-3, 4, -4]} />
              <gridHelper args={[12, 12, '#dbeafe', '#e2e8f0']} position={[0, -1.2, 0]} />
              <PreviewModel modelUrl={modelUrl} />
              <OrbitControls makeDefault enablePan enableRotate enableZoom />
            </Canvas>
          </Suspense>
        )}
      </div>
    </div>
  );
};

export default ModelPreviewPanel;
