import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, Circle, Ellipse, FabricImage, Line, PencilBrush, Rect } from 'fabric';
import { Check } from 'lucide-react';
import type { CanvasTool, UvFocusPoint } from '../types/design.ts';

type TextureCanvasSize = { width: number; height: number };
type ImageRequest = { requestId: number; imageUrl: string; label?: string };
type BaseTextureLayerRequest = ImageRequest & { workspaceId: string };
type Point = { x: number; y: number };

interface DesignerCanvasProps {
  tool: CanvasTool;
  sessionId: number | null;
  schemeId: string;
  baseModelId: number | null;
  uvTemplateUrl: string | null;
  uvTemplateMode?: string | null;
  textureCanvasSize?: TextureCanvasSize | null;
  strokeColor: string;
  fillColor: string;
  linkedUvFocus?: UvFocusPoint | null;
  onUvInspect?: (point: UvFocusPoint) => void;
  onAutoSave?: (schemeId: string, snapshot: string) => void;
  baseTextureLayer?: BaseTextureLayerRequest | null;
  insertAsset?: ImageRequest | null;
  showApplyEditedTexture?: boolean;
  canApplyEditedTexture?: boolean;
  applyEditedTexturePending?: boolean;
  onApplyEditedTexture?: (payload: { workspaceId: string; dataUrl: string }) => void;
  onWorkspaceContentChange?: (workspaceId: string, hasContent: boolean) => void;
}

const DEFAULT_TEXTURE_CANVAS_SIZE: TextureCanvasSize = { width: 2048, height: 1024 };
const DISPLAY_MAX_WIDTH = 1100;
const DISPLAY_MAX_HEIGHT = 620;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.1;
const SPECIAL_JSON_PROPS = ['name'];
const TEMPLATE_NAME = 'uv-template';
const BASE_TEXTURE_NAME = 'base-texture-layer';
const FOCUS_NAME = 'uv-focus-marker';

const clampZoom = (value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
const isValidSize = (value: TextureCanvasSize | null | undefined): value is TextureCanvasSize =>
  Boolean(value && Number.isFinite(value.width) && Number.isFinite(value.height) && value.width > 0 && value.height > 0);
const fitDisplaySize = (size: TextureCanvasSize): TextureCanvasSize => {
  const scale = Math.min(DISPLAY_MAX_WIDTH / size.width, DISPLAY_MAX_HEIGHT / size.height, 1);
  return { width: Math.max(1, Math.round(size.width * scale)), height: Math.max(1, Math.round(size.height * scale)) };
};
const sameBaseLayer = (left: BaseTextureLayerRequest | null | undefined, right: BaseTextureLayerRequest | null | undefined) =>
  left?.requestId === right?.requestId &&
  left?.workspaceId === right?.workspaceId &&
  left?.imageUrl === right?.imageUrl &&
  left?.label === right?.label;
const sameImageRequest = (left: ImageRequest | null | undefined, right: ImageRequest | null | undefined) =>
  left?.requestId === right?.requestId && left?.imageUrl === right?.imageUrl && left?.label === right?.label;
const isLocalDataLikeUrl = (value: string) => /^(data|blob):/i.test(value);
const blobToDataUrl = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result);
        return;
      }
      reject(new Error('Failed to convert blob to data URL.'));
    };
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read blob.'));
    reader.readAsDataURL(blob);
  });

const DesignerCanvas: React.FC<DesignerCanvasProps> = ({
  tool,
  sessionId,
  schemeId,
  baseModelId,
  uvTemplateUrl,
  uvTemplateMode,
  textureCanvasSize,
  strokeColor,
  fillColor,
  linkedUvFocus,
  onUvInspect,
  onAutoSave,
  baseTextureLayer,
  insertAsset,
  showApplyEditedTexture = false,
  canApplyEditedTexture = false,
  applyEditedTexturePending = false,
  onApplyEditedTexture,
  onWorkspaceContentChange,
}) => {
  const resolvedCanvasSize = useMemo(
    () => (isValidSize(textureCanvasSize) ? textureCanvasSize : DEFAULT_TEXTURE_CANVAS_SIZE),
    [textureCanvasSize],
  );
  const displayCanvasSize = useMemo(() => fitDisplaySize(resolvedCanvasSize), [resolvedCanvasSize]);
  const snapshotKey = useMemo(
    () => `${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}:${schemeId}`,
    [baseModelId, schemeId, sessionId],
  );
  const drawingEnabled = Boolean(uvTemplateUrl);

  const canvasHostRef = useRef<HTMLDivElement>(null);
  const canvasElementRef = useRef<HTMLCanvasElement | null>(null);
  const fabricCanvasRef = useRef<Canvas | null>(null);
  const drawingObjectRef = useRef<Rect | Ellipse | Line | null>(null);
  const startPointRef = useRef<Point | null>(null);
  const panStartRef = useRef<Point | null>(null);
  const spacePressedRef = useRef(false);
  const snapshotsRef = useRef<Record<string, string>>({});
  const lastSnapshotKeyRef = useRef(`${sessionId ?? 'no-session'}:${baseModelId ?? 'no-model'}:${schemeId}`);
  const toolRef = useRef(tool);
  const strokeColorRef = useRef(strokeColor);
  const fillColorRef = useRef(fillColor);
  const drawingEnabledRef = useRef(drawingEnabled);
  const baseTextureLayerRef = useRef<BaseTextureLayerRequest | null>(baseTextureLayer ?? null);
  const insertAssetRef = useRef<ImageRequest | null>(insertAsset ?? null);
  const autoSaveTimerRef = useRef<number | null>(null);
  const layerNoticeTimerRef = useRef<number | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [layerNotice, setLayerNotice] = useState<{ tone: 'success' | 'error'; message: string } | null>(null);

  const getObjectName = useCallback((item: { name?: string }) => item.name, []);
  const findNamedObject = useCallback(
    (canvas: Canvas, name: string) =>
      canvas.getObjects().find((item) => getObjectName(item as { name?: string }) === name) ?? null,
    [getObjectName],
  );
  const removeNamedObjects = useCallback(
    (canvas: Canvas, name: string) => {
      canvas
        .getObjects()
        .filter((item) => getObjectName(item as { name?: string }) === name)
        .forEach((item) => canvas.remove(item));
    },
    [getObjectName],
  );
  const setCanvasBackgroundImage = useCallback((canvas: Canvas, image?: FabricImage) => {
    (canvas as Canvas & { backgroundImage?: FabricImage }).backgroundImage = image;
    canvas.requestRenderAll();
  }, []);
  const serializeCanvas = useCallback((canvas: Canvas) => JSON.stringify(canvas.toObject(SPECIAL_JSON_PROPS)), []);
  const persistSnapshot = useCallback(
    (canvas: Canvas) => {
      if (!onAutoSave) {
        return;
      }
      const snapshot = serializeCanvas(canvas);
      snapshotsRef.current[snapshotKey] = snapshot;
      onAutoSave(schemeId, snapshot);
    },
    [onAutoSave, schemeId, serializeCanvas, snapshotKey],
  );
  const scheduleSnapshotPersist = useCallback(
    (canvas: Canvas, delayMs = 280) => {
      if (!onAutoSave) {
        return;
      }
      if (autoSaveTimerRef.current) {
        window.clearTimeout(autoSaveTimerRef.current);
      }
      autoSaveTimerRef.current = window.setTimeout(() => {
        autoSaveTimerRef.current = null;
        persistSnapshot(canvas);
      }, delayMs);
    },
    [onAutoSave, persistSnapshot],
  );
  const showLayerNotice = useCallback((tone: 'success' | 'error', message: string) => {
    setLayerNotice({ tone, message });
    if (layerNoticeTimerRef.current) {
      window.clearTimeout(layerNoticeTimerRef.current);
    }
    layerNoticeTimerRef.current = window.setTimeout(() => {
      layerNoticeTimerRef.current = null;
      setLayerNotice(null);
    }, 3600);
  }, []);
  const loadCanvasImage = useCallback(async (imageUrl: string) => {
    const loadFromUrl = async (url: string) => FabricImage.fromURL(url, { crossOrigin: 'anonymous' });
    if (isLocalDataLikeUrl(imageUrl)) {
      return loadFromUrl(imageUrl);
    }

    try {
      const response = await fetch(imageUrl, { credentials: 'omit' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const dataUrl = await blobToDataUrl(await response.blob());
      return await loadFromUrl(dataUrl);
    } catch (error) {
      console.warn('Falling back to direct image loading for canvas asset:', imageUrl, error);
      return loadFromUrl(imageUrl);
    }
  }, []);
  const preserveSerializedImageSource = useCallback((image: FabricImage, serializedUrl: string) => {
    const imageWithCustomSerializer = image as any;
    const originalToObject = imageWithCustomSerializer.toObject.bind(imageWithCustomSerializer) as (
      ...args: any[]
    ) => Record<string, unknown>;
    imageWithCustomSerializer.toObject = (...args: any[]) => ({
      ...originalToObject(...args),
      src: serializedUrl,
    });
    return image;
  }, []);
  const getInteractionScale = useCallback(
    (canvas: Canvas) => Math.max((canvas.getWidth() || 1) / Math.max(displayCanvasSize.width, 1), 1),
    [displayCanvasSize.width],
  );
  const normalizeSpecialLayerStack = useCallback(
    (canvas: Canvas) => {
      const template = findNamedObject(canvas, TEMPLATE_NAME);
      const baseTexture = findNamedObject(canvas, BASE_TEXTURE_NAME);
      const focus = findNamedObject(canvas, FOCUS_NAME);
      if (template) canvas.sendObjectToBack(template);
      if (baseTexture) canvas.sendObjectToBack(baseTexture);
      if (focus) canvas.bringObjectToFront(focus);
    },
    [findNamedObject],
  );
  const getCanvasHasUserContent = useCallback(
    (canvas: Canvas) =>
      canvas.getObjects().some((item) => {
        const name = getObjectName(item as { name?: string });
        return name !== TEMPLATE_NAME && name !== BASE_TEXTURE_NAME && name !== FOCUS_NAME;
      }),
    [getObjectName],
  );
  const emitWorkspaceContentChange = useCallback(
    (canvas: Canvas) => onWorkspaceContentChange?.(schemeId, getCanvasHasUserContent(canvas)),
    [getCanvasHasUserContent, onWorkspaceContentChange, schemeId],
  );
  const syncCanvasDimensions = useCallback(
    (canvas: Canvas) => {
      canvas.setDimensions({ width: resolvedCanvasSize.width, height: resolvedCanvasSize.height });
      canvas.setDimensions(
        { width: `${displayCanvasSize.width}px`, height: `${displayCanvasSize.height}px` },
        { cssOnly: true },
      );
      canvas.calcOffset();
    },
    [displayCanvasSize.height, displayCanvasSize.width, resolvedCanvasSize.height, resolvedCanvasSize.width],
  );
  const applyZoom = useCallback((canvas: Canvas, requestedZoom: number, anchor?: Point) => {
    const nextZoom = clampZoom(requestedZoom);
    const previousZoom = canvas.getZoom() || 1;
    const viewport: [number, number, number, number, number, number] = canvas.viewportTransform
      ? [...canvas.viewportTransform]
      : [previousZoom, 0, 0, previousZoom, 0, 0];
    const focus = anchor ?? { x: canvas.getWidth() / 2, y: canvas.getHeight() / 2 };
    viewport[4] = focus.x - ((focus.x - viewport[4]) * nextZoom) / previousZoom;
    viewport[5] = focus.y - ((focus.y - viewport[5]) * nextZoom) / previousZoom;
    viewport[0] = nextZoom;
    viewport[3] = nextZoom;
    canvas.setViewportTransform(viewport);
    canvas.requestRenderAll();
    setZoomLevel(nextZoom);
  }, []);
  const resetViewport = useCallback((canvas: Canvas) => {
    canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    canvas.requestRenderAll();
    setZoomLevel(1);
  }, []);
  const refreshTemplatePresentation = useCallback(
    (canvas: Canvas) => {
      const template = findNamedObject(canvas, TEMPLATE_NAME);
      if (!template) return;
      const hasBaseTexture = Boolean(baseTextureLayerRef.current && baseTextureLayerRef.current.workspaceId === schemeId);
      const isOutlineTemplate = uvTemplateMode === 'outline_template';
      const hideTemplateWhileTextureIsVisible = hasBaseTexture && isOutlineTemplate;
      template.set({
        // White-background outline templates visually overpower pale textures in
        // Fabric, so hide them entirely once a real texture layer is loaded.
        visible: !hideTemplateWhileTextureIsVisible,
        opacity: hideTemplateWhileTextureIsVisible ? 0 : hasBaseTexture ? 0.18 : 0.94,
        globalCompositeOperation: hasBaseTexture && !hideTemplateWhileTextureIsVisible ? 'source-over' : 'source-over',
      });
      normalizeSpecialLayerStack(canvas);
      canvas.requestRenderAll();
    },
    [findNamedObject, normalizeSpecialLayerStack, schemeId, uvTemplateMode],
  );
  const attachTemplate = useCallback(
    async (canvas: Canvas) => {
      removeNamedObjects(canvas, TEMPLATE_NAME);
      if (!uvTemplateUrl) {
        setTemplateError('Base model UV template is missing. Please prepare and lock a valid model first.');
        canvas.requestRenderAll();
        return;
      }
      try {
        setTemplateLoading(true);
        setTemplateError(null);
        const template = preserveSerializedImageSource(await loadCanvasImage(uvTemplateUrl), uvTemplateUrl);
        const safeWidth = template.width ?? resolvedCanvasSize.width;
        const safeHeight = template.height ?? resolvedCanvasSize.height;
        template.set({
          left: 0,
          top: 0,
          originX: 'left',
          originY: 'top',
          scaleX: resolvedCanvasSize.width / Math.max(safeWidth, 1),
          scaleY: resolvedCanvasSize.height / Math.max(safeHeight, 1),
          selectable: false,
          evented: false,
          excludeFromExport: true,
        });
        (template as { name?: string }).name = TEMPLATE_NAME;
        canvas.add(template);
        refreshTemplatePresentation(canvas);
      } catch (error) {
        console.error('Failed to load UV template:', error);
        setTemplateError('Failed to load UV template from backend.');
      } finally {
        setTemplateLoading(false);
      }
    },
    [
      loadCanvasImage,
      preserveSerializedImageSource,
      refreshTemplatePresentation,
      removeNamedObjects,
      resolvedCanvasSize.height,
      resolvedCanvasSize.width,
      uvTemplateUrl,
    ],
  );
  const syncBaseTextureLayer = useCallback(
    async (canvas: Canvas, requestedLayer: BaseTextureLayerRequest | null) => {
      removeNamedObjects(canvas, BASE_TEXTURE_NAME);
      setCanvasBackgroundImage(canvas);
      if (!requestedLayer || requestedLayer.workspaceId !== schemeId) {
        refreshTemplatePresentation(canvas);
        emitWorkspaceContentChange(canvas);
        return;
      }
      try {
        const image = preserveSerializedImageSource(
          await loadCanvasImage(requestedLayer.imageUrl),
          requestedLayer.imageUrl,
        );
        if (!sameBaseLayer(requestedLayer, baseTextureLayerRef.current)) return;
        const safeWidth = image.width ?? resolvedCanvasSize.width;
        const safeHeight = image.height ?? resolvedCanvasSize.height;
        image.set({
          left: 0,
          top: 0,
          originX: 'left',
          originY: 'top',
          scaleX: resolvedCanvasSize.width / Math.max(safeWidth, 1),
          scaleY: resolvedCanvasSize.height / Math.max(safeHeight, 1),
          selectable: false,
          evented: false,
        });
        setCanvasBackgroundImage(canvas, image);
        refreshTemplatePresentation(canvas);
        emitWorkspaceContentChange(canvas);
        scheduleSnapshotPersist(canvas, 80);
        showLayerNotice('success', `Loaded texture layer: ${requestedLayer.label ?? 'Current texture'}`);
      } catch (error) {
        console.error('Failed to attach base texture layer to canvas:', error);
        showLayerNotice('error', 'Failed to load the selected texture into the canvas.');
      }
    },
    [
      emitWorkspaceContentChange,
      loadCanvasImage,
      preserveSerializedImageSource,
      refreshTemplatePresentation,
      removeNamedObjects,
      resolvedCanvasSize.height,
      resolvedCanvasSize.width,
      scheduleSnapshotPersist,
      schemeId,
      setCanvasBackgroundImage,
      showLayerNotice,
    ],
  );
  const applyCurrentTool = useCallback(
    (canvas: Canvas) => {
      if (!drawingEnabledRef.current) {
        canvas.isDrawingMode = false;
        return;
      }
      if (toolRef.current === 'pencil' || toolRef.current === 'eraser') {
        const scale = getInteractionScale(canvas);
        const brush = new PencilBrush(canvas);
        brush.width = (toolRef.current === 'eraser' ? 18 : 3) * scale;
        brush.color = toolRef.current === 'eraser' ? '#ffffff' : strokeColorRef.current;
        canvas.isDrawingMode = true;
        canvas.freeDrawingBrush = brush;
        return;
      }
      canvas.isDrawingMode = false;
    },
    [getInteractionScale],
  );
  const setCanvasCursor = useCallback((canvas: Canvas, value: string) => {
    canvas.defaultCursor = value;
    canvas.hoverCursor = value;
    canvas.moveCursor = value;
  }, []);
  const syncUvFocusMarker = useCallback(
    (canvas: Canvas, focus: UvFocusPoint | null) => {
      removeNamedObjects(canvas, FOCUS_NAME);
      if (!focus) {
        canvas.requestRenderAll();
        return;
      }
      const scale = getInteractionScale(canvas);
      const ring = new Circle({
        left: focus.u * canvas.getWidth(),
        top: (1 - focus.v) * canvas.getHeight(),
        radius: 14 * scale,
        originX: 'center',
        originY: 'center',
        fill: 'transparent',
        stroke: focus.source === 'uv' ? '#2563eb' : '#f97316',
        strokeWidth: Math.max(3 * scale, 2),
        selectable: false,
        evented: false,
        excludeFromExport: true,
      });
      (ring as { name?: string }).name = FOCUS_NAME;
      canvas.add(ring);
      normalizeSpecialLayerStack(canvas);
      canvas.requestRenderAll();
    },
    [getInteractionScale, normalizeSpecialLayerStack, removeNamedObjects],
  );

  useEffect(() => {
    toolRef.current = tool;
    strokeColorRef.current = strokeColor;
    fillColorRef.current = fillColor;
    drawingEnabledRef.current = drawingEnabled;
    baseTextureLayerRef.current = baseTextureLayer ?? null;
    insertAssetRef.current = insertAsset ?? null;
  }, [baseTextureLayer, drawingEnabled, fillColor, insertAsset, strokeColor, tool]);

  useEffect(() => {
    if (!canvasHostRef.current || fabricCanvasRef.current) return;
    const host = canvasHostRef.current;
    const node = document.createElement('canvas');
    canvasElementRef.current = node;
    host.replaceChildren(node);
    const canvas = new Canvas(node, {
      width: resolvedCanvasSize.width,
      height: resolvedCanvasSize.height,
      backgroundColor: '#ffffff',
      selection: true,
      preserveObjectStacking: true,
    });
    fabricCanvasRef.current = canvas;
    syncCanvasDimensions(canvas);
    setCanvasCursor(canvas, 'default');
    applyCurrentTool(canvas);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || spacePressedRef.current) return;
      event.preventDefault();
      spacePressedRef.current = true;
      setCanvasCursor(canvas, 'grab');
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code !== 'Space') return;
      spacePressedRef.current = false;
      panStartRef.current = null;
      canvas.selection = true;
      setCanvasCursor(canvas, 'default');
    };
    const onMouseDown = (eventInfo: { e: MouseEvent }) => {
      const shouldPan = spacePressedRef.current || eventInfo.e.button === 1;
      if (shouldPan) {
        const viewportPoint = canvas.getViewportPoint(eventInfo.e);
        panStartRef.current = { x: viewportPoint.x, y: viewportPoint.y };
        canvas.selection = false;
        setCanvasCursor(canvas, 'grabbing');
        return;
      }
      if (!drawingEnabledRef.current || canvas.isDrawingMode) return;
      const activeTool = toolRef.current;
      const pointer = canvas.getScenePoint(eventInfo.e);
      if (activeTool === 'select') {
        onUvInspect?.({
          u: Math.min(1, Math.max(0, pointer.x / canvas.getWidth())),
          v: Math.min(1, Math.max(0, 1 - pointer.y / canvas.getHeight())),
          source: 'uv',
          token: Date.now(),
        });
        return;
      }
      if (activeTool !== 'rect' && activeTool !== 'ellipse' && activeTool !== 'line') return;
      const scale = getInteractionScale(canvas);
      startPointRef.current = { x: pointer.x, y: pointer.y };
      if (activeTool === 'rect') {
        const rect = new Rect({
          left: pointer.x,
          top: pointer.y,
          width: 1,
          height: 1,
          fill: 'transparent',
          stroke: strokeColorRef.current,
          strokeWidth: 2 * scale,
        });
        drawingObjectRef.current = rect;
        canvas.add(rect);
        return;
      }
      if (activeTool === 'ellipse') {
        const ellipse = new Ellipse({
          left: pointer.x,
          top: pointer.y,
          rx: 1,
          ry: 1,
          fill: `${fillColorRef.current}44`,
          stroke: strokeColorRef.current,
          strokeWidth: 2 * scale,
        });
        drawingObjectRef.current = ellipse;
        canvas.add(ellipse);
        return;
      }
      const line = new Line([pointer.x, pointer.y, pointer.x, pointer.y], {
        stroke: strokeColorRef.current,
        strokeWidth: 2 * scale,
      });
      drawingObjectRef.current = line;
      canvas.add(line);
    };
    const onMouseMove = (eventInfo: { e: MouseEvent }) => {
      if (panStartRef.current) {
        const viewportPoint = canvas.getViewportPoint(eventInfo.e);
        const viewport = canvas.viewportTransform
          ? [...canvas.viewportTransform]
          : [canvas.getZoom() || 1, 0, 0, canvas.getZoom() || 1, 0, 0];
        viewport[4] += viewportPoint.x - panStartRef.current.x;
        viewport[5] += viewportPoint.y - panStartRef.current.y;
        canvas.setViewportTransform(viewport as [number, number, number, number, number, number]);
        canvas.requestRenderAll();
        panStartRef.current = { x: viewportPoint.x, y: viewportPoint.y };
        return;
      }
      if (!drawingObjectRef.current || !startPointRef.current) return;
      const pointer = canvas.getScenePoint(eventInfo.e);
      const startPoint = startPointRef.current;
      if (drawingObjectRef.current instanceof Rect) {
        drawingObjectRef.current.set({
          left: Math.min(pointer.x, startPoint.x),
          top: Math.min(pointer.y, startPoint.y),
          width: Math.abs(pointer.x - startPoint.x),
          height: Math.abs(pointer.y - startPoint.y),
        });
      } else if (drawingObjectRef.current instanceof Ellipse) {
        drawingObjectRef.current.set({
          left: Math.min(pointer.x, startPoint.x),
          top: Math.min(pointer.y, startPoint.y),
          rx: Math.abs(pointer.x - startPoint.x) / 2,
          ry: Math.abs(pointer.y - startPoint.y) / 2,
          originX: 'left',
          originY: 'top',
        });
      } else if (drawingObjectRef.current instanceof Line) {
        drawingObjectRef.current.set({ x2: pointer.x, y2: pointer.y });
      }
      drawingObjectRef.current.setCoords();
      canvas.renderAll();
    };
    const onMouseUp = () => {
      if (panStartRef.current) {
        panStartRef.current = null;
        canvas.selection = true;
        setCanvasCursor(canvas, spacePressedRef.current ? 'grab' : 'default');
        return;
      }
      drawingObjectRef.current = null;
      startPointRef.current = null;
    };
    const onMouseWheel = (eventInfo: { e: WheelEvent }) => {
      if (!eventInfo.e.ctrlKey && !eventInfo.e.metaKey) return;
      eventInfo.e.preventDefault();
      eventInfo.e.stopPropagation();
      const viewportPoint = canvas.getViewportPoint(eventInfo.e);
      applyZoom(canvas, (canvas.getZoom() || 1) * Math.pow(0.998, eventInfo.e.deltaY), {
        x: viewportPoint.x,
        y: viewportPoint.y,
      });
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    canvas.on('mouse:down', onMouseDown as never);
    canvas.on('mouse:move', onMouseMove as never);
    canvas.on('mouse:up', onMouseUp as never);
    canvas.on('mouse:wheel', onMouseWheel as never);
    const handleCanvasMutation = () => {
      emitWorkspaceContentChange(canvas);
      scheduleSnapshotPersist(canvas);
    };
    canvas.on('object:added', handleCanvasMutation as never);
    canvas.on('object:removed', handleCanvasMutation as never);
    canvas.on('object:modified', handleCanvasMutation as never);

    return () => {
      canvas.off('mouse:down', onMouseDown as never);
      canvas.off('mouse:move', onMouseMove as never);
      canvas.off('mouse:up', onMouseUp as never);
      canvas.off('mouse:wheel', onMouseWheel as never);
      canvas.off('object:added', handleCanvasMutation as never);
      canvas.off('object:removed', handleCanvasMutation as never);
      canvas.off('object:modified', handleCanvasMutation as never);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      canvas.dispose();
      fabricCanvasRef.current = null;
      if (canvasElementRef.current && host.contains(canvasElementRef.current)) host.removeChild(canvasElementRef.current);
      canvasElementRef.current = null;
    };
  }, [
    applyCurrentTool,
    applyZoom,
    attachTemplate,
    emitWorkspaceContentChange,
    getInteractionScale,
    onUvInspect,
    resolvedCanvasSize.height,
    resolvedCanvasSize.width,
    setCanvasCursor,
    syncBaseTextureLayer,
    syncCanvasDimensions,
    scheduleSnapshotPersist,
  ]);

  useEffect(() => {
    if (autoSaveTimerRef.current) {
      window.clearTimeout(autoSaveTimerRef.current);
      autoSaveTimerRef.current = null;
    }
  }, [snapshotKey]);

  useEffect(
    () => () => {
      if (autoSaveTimerRef.current) {
        window.clearTimeout(autoSaveTimerRef.current);
      }
      if (layerNoticeTimerRef.current) {
        window.clearTimeout(layerNoticeTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    syncCanvasDimensions(canvas);
    resetViewport(canvas);
    refreshTemplatePresentation(canvas);
  }, [refreshTemplatePresentation, resetViewport, syncCanvasDimensions]);

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    applyCurrentTool(canvas);
  }, [applyCurrentTool, drawingEnabled, strokeColor, tool]);

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    let cancelled = false;
    snapshotsRef.current[lastSnapshotKeyRef.current] = serializeCanvas(canvas);
    resetViewport(canvas);
    const storageKey = `co-track:snapshot:${sessionId ?? 'no-session'}:${baseModelId ?? 'none'}:${schemeId}`;
    const nextSnapshot = snapshotsRef.current[snapshotKey] ?? window.localStorage.getItem(storageKey) ?? undefined;
    const restore = async () => {
      if (nextSnapshot) {
        await canvas.loadFromJSON(nextSnapshot);
      } else {
        canvas.clear();
        canvas.backgroundColor = '#ffffff';
      }
      if (cancelled) return;
      await attachTemplate(canvas);
      if (cancelled) return;
      await syncBaseTextureLayer(canvas, baseTextureLayerRef.current);
      if (cancelled) return;
      applyCurrentTool(canvas);
      canvas.renderAll();
      emitWorkspaceContentChange(canvas);
    };
    void restore();
    lastSnapshotKeyRef.current = snapshotKey;
    return () => {
      cancelled = true;
    };
  }, [
    applyCurrentTool,
    attachTemplate,
    baseModelId,
    emitWorkspaceContentChange,
    resetViewport,
    schemeId,
    sessionId,
    serializeCanvas,
    snapshotKey,
    syncBaseTextureLayer,
  ]);

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    syncUvFocusMarker(canvas, linkedUvFocus ?? null);
  }, [linkedUvFocus, syncUvFocusMarker]);

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas || !onAutoSave) return;
    const timer = window.setInterval(() => {
      persistSnapshot(canvas);
    }, 30000);
    return () => window.clearInterval(timer);
  }, [onAutoSave, persistSnapshot]);

  useEffect(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    let cancelled = false;
    void (async () => {
      await syncBaseTextureLayer(canvas, baseTextureLayer ?? null);
      if (!cancelled) emitWorkspaceContentChange(canvas);
    })();
    return () => {
      cancelled = true;
    };
  }, [baseTextureLayer, emitWorkspaceContentChange, syncBaseTextureLayer]);

  useEffect(() => {
    if (!insertAsset) return;
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    let cancelled = false;
    void (async () => {
      try {
        const image = preserveSerializedImageSource(await loadCanvasImage(insertAsset.imageUrl), insertAsset.imageUrl);
        if (cancelled || !sameImageRequest(insertAsset, insertAssetRef.current)) return;
        const safeWidth = image.width ?? 512;
        const safeHeight = image.height ?? 512;
        const canvasWidth = canvas.getWidth();
        const canvasHeight = canvas.getHeight();
        const scale = Math.min((canvasWidth * 0.42) / safeWidth, (canvasHeight * 0.42) / safeHeight, 1);
        image.set({
          left: (canvasWidth - safeWidth * scale) / 2,
          top: (canvasHeight - safeHeight * scale) / 2,
          selectable: true,
          evented: true,
        });
        image.scale(scale);
        (image as { name?: string }).name = insertAsset.label ?? 'generated-pattern-asset';
        canvas.add(image);
        canvas.setActiveObject(image);
        normalizeSpecialLayerStack(canvas);
        canvas.renderAll();
        emitWorkspaceContentChange(canvas);
        scheduleSnapshotPersist(canvas, 80);
      } catch (error) {
        console.error('Failed to insert generated asset into canvas:', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    emitWorkspaceContentChange,
    insertAsset,
    loadCanvasImage,
    normalizeSpecialLayerStack,
    preserveSerializedImageSource,
    scheduleSnapshotPersist,
  ]);

  const handleApplyEditedTextureClick = useCallback(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas || !onApplyEditedTexture) return;
    const hiddenObjects = canvas.getObjects().filter((item) => {
      const name = getObjectName(item as { name?: string });
      return name === TEMPLATE_NAME || name === FOCUS_NAME;
    });
    const visibility = hiddenObjects.map((item) => item.visible);
    hiddenObjects.forEach((item) => {
      item.visible = false;
    });
    canvas.renderAll();
    try {
      onApplyEditedTexture({ workspaceId: schemeId, dataUrl: canvas.toDataURL({ format: 'png', multiplier: 1 }) });
    } finally {
      hiddenObjects.forEach((item, index) => {
        item.visible = visibility[index];
      });
      canvas.renderAll();
    }
  }, [getObjectName, onApplyEditedTexture, schemeId]);

  const handleZoomIn = useCallback(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    applyZoom(canvas, (canvas.getZoom() || 1) + ZOOM_STEP);
  }, [applyZoom]);
  const handleZoomOut = useCallback(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    applyZoom(canvas, (canvas.getZoom() || 1) - ZOOM_STEP);
  }, [applyZoom]);
  const handleZoomReset = useCallback(() => {
    const canvas = fabricCanvasRef.current;
    if (!canvas) return;
    resetViewport(canvas);
  }, [resetViewport]);

  return (
    <div className="relative flex h-full w-full items-center justify-center bg-slate-100/80 p-4">
      <div
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        style={{ width: displayCanvasSize.width, height: displayCanvasSize.height }}
      >
        <div ref={canvasHostRef} style={{ width: displayCanvasSize.width, height: displayCanvasSize.height }} />
      </div>
      <div className="absolute right-8 top-8 z-20 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white/95 p-1 text-xs text-slate-700 shadow-sm">
        {showApplyEditedTexture ? (
          <button
            type="button"
            onClick={handleApplyEditedTextureClick}
            disabled={!canApplyEditedTexture || applyEditedTexturePending}
            className={`mr-1 inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-semibold transition ${
              canApplyEditedTexture && !applyEditedTexturePending
                ? 'bg-slate-900 text-white hover:bg-slate-800'
                : 'cursor-not-allowed bg-slate-100 text-slate-400'
            }`}
          >
            {applyEditedTexturePending ? 'Applying...' : <><Check size={14} /> Apply Edited Texture</>}
          </button>
        ) : null}
        <button type="button" onClick={handleZoomOut} className="rounded px-2 py-1 font-semibold text-slate-700 hover:bg-slate-100" aria-label="Zoom out canvas">-</button>
        <button type="button" onClick={handleZoomReset} className="rounded px-2 py-1 font-semibold text-slate-600 hover:bg-slate-100" aria-label="Reset canvas zoom">{Math.round(zoomLevel * 100)}%</button>
        <button type="button" onClick={handleZoomIn} className="rounded px-2 py-1 font-semibold text-slate-700 hover:bg-slate-100" aria-label="Zoom in canvas">+</button>
      </div>
      <div className="absolute bottom-8 left-8 z-10 max-w-[50%] rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-[11px] text-slate-600 shadow-sm">
        {drawingEnabled
          ? `UV canvas ${resolvedCanvasSize.width} x ${resolvedCanvasSize.height}. Use Select to inspect UV <-> 3D. Hold Space and drag to pan. Ctrl + wheel to zoom.`
          : 'Waiting for a valid UV template.'}
      </div>
      {templateLoading ? (
        <div className="absolute left-8 top-20 z-10 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-[11px] text-blue-700">Loading UV template from backend...</div>
      ) : null}
      {templateError ? (
        <div className="absolute left-8 top-20 z-10 max-w-sm rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">{templateError}</div>
      ) : null}
      {layerNotice ? (
        <div
          className={`absolute left-8 top-32 z-10 max-w-sm rounded-lg px-3 py-2 text-[11px] shadow-sm ${
            layerNotice.tone === 'success'
              ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border border-rose-200 bg-rose-50 text-rose-700'
          }`}
        >
          {layerNotice.message}
        </div>
      ) : null}
      <div className="absolute bottom-8 right-8 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-[11px] text-slate-600">
        Layer tip: base texture / pattern / text / annotation.
      </div>
    </div>
  );
};

export default DesignerCanvas;
