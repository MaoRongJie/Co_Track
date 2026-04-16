import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Bounds, OrbitControls, useGLTF } from '@react-three/drei';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import {
  AlertCircle,
  Box,
  Check,
  Link2,
  LoaderCircle,
  MousePointerClick,
  Paintbrush,
  Sparkles,
  Plus,
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
import type { BaseModelMeta, TexturedModel, UvFocusPoint } from '../types/design.ts';

interface Stage2LinkedPreviewProps {
  baseModel: BaseModelMeta | null;
  linkedUvFocus: UvFocusPoint | null;
  onLinkedUvFocusChange: (point: UvFocusPoint | null) => void;
  texturedModels?: TexturedModel[];
  textureModelsStatus?: 'idle' | 'queued' | 'processing' | 'completed' | 'failed';
  selectedTexturedSchemeId?: string | null;
  selectedPreviewMode?: 'meshy' | 'edited';
  selectedTexturedModelUrl?: string | null;
  onSelectTexturedModel?: (schemeId: string) => void;
  onAddTextureToCanvas?: (schemeId: string) => void;
  onPreviewModeChange?: (mode: 'meshy' | 'edited') => void;
}

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
  linkedUvFocus,
  onLinkedUvFocusChange,
  texturedModels = [],
  textureModelsStatus = 'idle',
  selectedTexturedSchemeId,
  selectedPreviewMode = 'meshy',
  selectedTexturedModelUrl,
  onSelectTexturedModel,
  onAddTextureToCanvas,
  onPreviewModeChange,
}) => {
  const [selection, setSelection] = useState<TriangleSelection | null>(null);

  const previewModelUrl = selectedTexturedModelUrl || baseModel?.modelUrl || null;
  const hasTexturedModels = texturedModels.length > 0;
  const selectedTexturedModel =
    selectedTexturedSchemeId
      ? texturedModels.find((model) => model.schemeId === selectedTexturedSchemeId) ?? null
      : null;
  const canAddPreviewTextureToCanvas = Boolean(
    selectedTexturedModel?.textureMaps?.baseColor || selectedTexturedModel?.editedVariant?.baseColorUrl,
  );
  const previewUsesRemoteMeshyAsset = Boolean(
    previewModelUrl && /^https?:\/\/assets\.meshy\.ai\//i.test(previewModelUrl),
  );

  if (!baseModel?.modelUrl) {
    return (
      <aside className="z-20 flex w-[22rem] shrink-0 flex-col border-l border-slate-200 bg-white p-4">
        <div className="flex h-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-5 text-center">
          <div className="rounded-2xl bg-slate-100 p-4 text-slate-500">
            <Box size={26} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-700">3D linked preview unavailable</p>
            <p className="mt-1 text-xs text-slate-500">Prepare and lock a valid base model first.</p>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="z-20 flex w-[22rem] shrink-0 flex-col border-l border-slate-200 bg-white">
      <div className="flex-1 overflow-y-auto p-4">
        {/* Header */}
        <div className="mb-4 flex items-center gap-2">
          <Link2 size={16} className="text-blue-600" />
          <h3 className="text-sm font-semibold text-slate-800">
            {selectedTexturedModel ? 'Textured Preview' : 'Linked 3D Preview'}
          </h3>
        </div>

        {/* 3D Preview */}
        <div className="relative h-72 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-sm">
          {selectedTexturedModel ? (
            <div className="absolute right-2 top-2 z-20">
              <button
                type="button"
                onClick={() => canAddPreviewTextureToCanvas && onAddTextureToCanvas?.(selectedTexturedModel.schemeId)}
                disabled={!canAddPreviewTextureToCanvas}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold shadow-sm transition ${
                  canAddPreviewTextureToCanvas
                    ? 'bg-slate-900 text-white hover:bg-slate-800'
                    : 'cursor-not-allowed bg-slate-100 text-slate-400 hover:bg-slate-100'
                }`}
              >
                <Plus size={12} />
                Add to Canvas
              </button>
            </div>
          ) : null}
          {selectedTexturedModel?.editedVariant?.modelUrl ? (
            <div className="absolute left-2 top-2 z-20 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white/95 p-1 text-[11px] text-slate-700 shadow-sm">
              <button
                type="button"
                onClick={() => onPreviewModeChange?.('meshy')}
                className={`rounded px-2.5 py-1 font-semibold transition ${
                  selectedPreviewMode === 'meshy'
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                Meshy
              </button>
              <button
                type="button"
                onClick={() => onPreviewModeChange?.('edited')}
                className={`flex items-center gap-1 rounded px-2.5 py-1 font-semibold transition ${
                  selectedPreviewMode === 'edited'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <Paintbrush size={11} />
                Edited
              </button>
            </div>
          ) : null}

          {previewUsesRemoteMeshyAsset ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center">
              <div className="rounded-2xl bg-amber-50 p-4 text-amber-500">
                <AlertCircle size={24} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">Preview unavailable for remote Meshy asset</p>
                <p className="mt-1 text-xs text-slate-500">
                  The backend needs to cache the generated GLB locally before the browser can preview it.
                </p>
              </div>
            </div>
          ) : (
            <AppErrorBoundary key={previewModelUrl ?? 'empty'} title="3D preview failed">
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                    <LoaderCircle size={14} className="animate-spin" />
                    Loading 3D preview...
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
            <div className="mb-2 flex items-start gap-2">
              <MousePointerClick size={13} className="mt-0.5 text-slate-500" />
              <p>Click UV canvas or the 3D model to inspect UV mapping.</p>
            </div>
            <div className="flex items-center justify-between">
              <span>Mesh: <span className="font-semibold text-slate-800">{selection?.meshName ?? '-'}</span></span>
              <span>UV: <span className="font-semibold text-slate-800">{uvToLabel(linkedUvFocus ? { u: linkedUvFocus.u, v: linkedUvFocus.v } : null)}</span></span>
            </div>
          </div>
        ) : null}

        {/* Textured Model Cards */}
        <div className="mt-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Paintbrush size={14} className="text-blue-600" />
              <h4 className="text-xs font-semibold text-slate-700">Textured Results</h4>
            </div>
            {hasTexturedModels && selectedTexturedModel ? (
              <button
                type="button"
                onClick={() => onSelectTexturedModel?.('')}
                className="text-[10px] text-slate-500 hover:text-blue-600 transition"
                onClickCapture={(e) => {
                  e.stopPropagation();
                  // Reset to original model by clearing selection
                  // We pass empty string to clear; parent should handle
                }}
              >
                Show Original
              </button>
            ) : null}
          </div>

          {hasTexturedModels ? (
            <div className="grid grid-cols-3 gap-2">
              {texturedModels.map((model) => {
                const isSelected = model.schemeId === selectedTexturedSchemeId;
                const isCompleted = model.status === 'completed';
                const isFailed = model.status === 'failed';

                return (
                  <div
                    key={model.schemeId}
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
                    {isSelected ? (
                      <div className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-600 text-white">
                        <Check size={10} />
                      </div>
                    ) : null}

                    <button
                      type="button"
                      onClick={() => isCompleted && onSelectTexturedModel?.(model.schemeId)}
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
                        ) : isFailed ? (
                          <Box size={16} />
                        ) : (
                          <Box size={16} />
                        )}
                      </div>

                      <span className={`text-[10px] font-medium leading-tight ${
                        isSelected ? 'text-blue-700' :
                        isFailed ? 'text-red-600' :
                        'text-slate-600'
                      }`}>
                        {model.title || model.schemeId}
                      </span>
                      {model.editedVariant?.modelUrl ? (
                        <span className="text-[9px] font-medium text-emerald-600">Edited</span>
                      ) : null}
                    </button>

                    {isFailed ? (
                      <span className="text-[9px] text-red-500" title={model.errorMessage ?? 'Meshy task failed'}>
                        {model.errorMessage ? (model.errorMessage.length > 72 ? `${model.errorMessage.slice(0, 72)}...` : model.errorMessage) : 'Failed'}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50 py-5 text-center">
              {textureModelsStatus === 'queued' || textureModelsStatus === 'processing' ? (
                <>
                  <LoaderCircle size={18} className="animate-spin text-blue-500" />
                  <p className="text-[11px] text-slate-500">
                    {textureModelsStatus === 'queued'
                      ? 'Texture generation has been queued. Results will appear here shortly.'
                      : 'Generating textured model results in the background.'}
                  </p>
                </>
              ) : textureModelsStatus === 'failed' ? (
                <>
                  <Box size={18} className="text-red-400" />
                  <p className="text-[11px] text-red-500">Texture generation failed. Please check the latest error and try again.</p>
                </>
              ) : (
                <>
                  <Sparkles size={18} className="text-slate-400" />
                  <p className="text-[11px] text-slate-500">Generate model textures to see three results here.</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};

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
