import React, { Suspense, useMemo } from 'react';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import { Box, LoaderCircle } from 'lucide-react';

interface ModelPreviewPanelProps {
  modelUrl: string | null;
  title?: string;
  subtitle?: string | null;
  loading?: boolean;
  framed?: boolean;
  previewClassName?: string;
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
      {subtitle ? <p className="mt-1 text-xs text-slate-500">{subtitle}</p> : null}
    </div>
  </div>
);

class PreviewErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode; resetKey: string | null },
  { hasError: boolean; resetKey: string | null }
> {
  state = { hasError: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  static getDerivedStateFromProps(
    props: { resetKey: string | null },
    state: { hasError: boolean; resetKey: string | null },
  ): { hasError: boolean; resetKey: string | null } | null {
    if (props.resetKey !== state.resetKey) {
      return { hasError: false, resetKey: props.resetKey };
    }
    return null;
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

const ModelPreviewPanel: React.FC<ModelPreviewPanelProps> = ({
  modelUrl,
  title = '基础模型预览',
  subtitle,
  loading = false,
  framed = true,
  previewClassName,
}) => {
  const fallbackSubtitle =
    subtitle ?? (loading ? '处理中...' : 'GLB / GLTF');
  const previewClass = previewClassName ?? 'relative h-80 bg-gradient-to-br from-slate-100 via-white to-blue-50';
  const header = (
    <div className={`flex items-center justify-between ${framed ? 'border-b border-slate-200 px-4 py-3' : ''}`}>
      <div>
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
        {fallbackSubtitle ? <p className="mt-1 text-xs text-slate-500">{fallbackSubtitle}</p> : null}
      </div>
      {loading ? (
        <span className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
          <LoaderCircle size={13} className="animate-spin" />
          处理中
        </span>
      ) : null}
    </div>
  );
  const preview = (
    <div className={previewClass}>
      {!modelUrl ? (
        <PreviewEmptyState title="暂无预览" subtitle={fallbackSubtitle} />
      ) : (
        <PreviewErrorBoundary
          resetKey={modelUrl}
          fallback={<PreviewEmptyState title="模型加载失败" subtitle="请重新上传 GLB / GLTF 文件。" />}
        >
          <Suspense fallback={<PreviewEmptyState title="加载中..." subtitle="" />}>
            <Canvas key={modelUrl} camera={{ position: [3.6, 2.2, 4.6], fov: 42 }}>
              <color attach="background" args={['#f8fafc']} />
              <ambientLight intensity={0.95} />
              <directionalLight intensity={1.15} position={[4, 7, 5]} />
              <directionalLight intensity={0.45} position={[-3, 4, -4]} />
              <gridHelper args={[12, 12, '#dbeafe', '#e2e8f0']} position={[0, -1.2, 0]} />
              <PreviewModel modelUrl={modelUrl} />
              <OrbitControls makeDefault enablePan enableRotate enableZoom />
            </Canvas>
          </Suspense>
        </PreviewErrorBoundary>
      )}
    </div>
  );

  if (!framed) {
    return (
      <div>
        {header}
        {preview}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      {header}
      {preview}
    </div>
  );
};

export default ModelPreviewPanel;
