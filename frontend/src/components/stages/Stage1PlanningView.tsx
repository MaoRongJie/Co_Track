import React from 'react';
import {
  Bot,
  CloudUpload,
  Database,
  FileText,
  Lock,
  Sparkles,
  Wand2,
} from 'lucide-react';
import ModelPreviewPanel from '../ModelPreviewPanel.tsx';
import type {
  BaseModelMeta,
  BaseModelSource,
  DesignBrief,
  ProductCategory,
  ProductProfile,
  ProductProfileValue,
} from '../../types/design.ts';
import type { SessionStage } from '../../types/meeting.ts';

interface Stage1PlanningViewProps {
  isHost: boolean;
  backendStage: SessionStage;
  modelTaskStatus: string | null;
  modelTaskProgress: number;
  modelPipelineStage: string | null;
  modelProgressMessage: string | null;
  preparingBaseModel: boolean;
  designGoal: string;
  onDesignGoalChange: (value: string) => void;
  productCategory: ProductCategory;
  onProductCategoryChange: (value: ProductCategory) => void;
  modelSource: BaseModelSource;
  onModelSourceChange: (value: BaseModelSource) => void;
  productProfile: ProductProfile;
  onProductProfileChange: (profile: ProductProfile) => void;
  brief: DesignBrief | null;
  onParseBrief: () => void;
  baseModel: BaseModelMeta | null;
  baseModelLocked: boolean;
  onLockBaseModel: () => void;
  onUploadFileSelected: (file: File | null) => void;
  uploadedFileName: string | null;
}

const categoryOptions: Array<{ value: ProductCategory; label: string }> = [
  { value: 'high_speed_train', label: 'High-speed Train' },
  { value: 'intercity_train', label: 'Intercity Train' },
  { value: 'metro_vehicle', label: 'Metro Vehicle' },
  { value: 'automobile', label: 'Automobile' },
  { value: 'home_appliance', label: 'Home Appliance' },
  { value: 'industrial_other', label: 'Industrial Other' },
];

const sourceOptions: Array<{ value: BaseModelSource; label: string; icon: React.ReactNode }> = [
  { value: 'upload', label: 'Upload 3D Model', icon: <CloudUpload size={14} /> },
  { value: 'library', label: 'Select From Library', icon: <Database size={14} /> },
  { value: 'generate', label: 'Generate Approx Model', icon: <Wand2 size={14} /> },
];

const precisionTextMap = {
  authoritative: 'Authoritative',
  standard: 'Standard',
  approximate: 'Approximate',
} as const;

const sourceTagMap = {
  upload: 'Upload',
  library: 'Library',
  generate: 'Generate',
} as const;

const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
};

const Stage1PlanningView: React.FC<Stage1PlanningViewProps> = ({
  isHost,
  backendStage,
  modelTaskStatus,
  modelTaskProgress,
  modelPipelineStage,
  modelProgressMessage,
  preparingBaseModel,
  designGoal,
  onDesignGoalChange,
  productCategory,
  onProductCategoryChange,
  modelSource,
  onModelSourceChange,
  productProfile,
  onProductProfileChange,
  brief,
  onParseBrief,
  baseModel,
  baseModelLocked,
  onLockBaseModel,
  onUploadFileSelected,
  uploadedFileName,
}) => {
  const safeTaskProgress = Math.max(0, Math.min(100, toFiniteNumber(modelTaskProgress) ?? 0));
  const baseModelSurfaceArea = toFiniteNumber(baseModel?.surfaceAreaM2);
  const baseModelUvPixels = toFiniteNumber(baseModel?.paintableUvPixels);
  const inspection = baseModel?.mappingMeta?.inspection;
  const showTaskPanel = preparingBaseModel || Boolean(modelTaskStatus);
  const hasBaseModel = Boolean(baseModel);
  const baseModelIdText = hasBaseModel ? String(baseModel?.baseModelId ?? '-') : '-';
  const baseModelSourceText = hasBaseModel
    ? (sourceTagMap[baseModel?.sourceType ?? 'library'] ?? String(baseModel?.sourceType ?? '-'))
    : '-';
  const baseModelPrecisionText = hasBaseModel
    ? (precisionTextMap[baseModel?.precisionLevel ?? 'standard'] ?? String(baseModel?.precisionLevel ?? '-'))
    : '-';
  const baseModelLicenseText = hasBaseModel
    ? `${baseModel?.licenseScope ?? '-'} / GLB ${baseModel?.exportGlbAllowed ? 'Allowed' : 'Restricted'}`
    : '-';
  const uploadCardSubtitle = uploadedFileName
    ? `Current file: ${uploadedFileName}`
    : 'Choose a GLB/GLTF file. The system will process it automatically and then you can lock it as the base model.';

  const updateProfile = (key: string, value: ProductProfileValue) => {
    onProductProfileChange({
      ...productProfile,
      [key]: value,
    });
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50">
      <div className="mx-auto grid w-full max-w-7xl gap-6 p-6 lg:grid-cols-[1.25fr_1fr]">
        <section className="space-y-6">
          {!isHost ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              You are currently in designer/observer role. Stage-1 parse, model prepare, lock, and stage advance are
              host-only operations.
            </div>
          ) : null}

          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <FileText size={18} className="text-blue-600" />
              <h2 className="text-base font-semibold text-slate-800">Stage 1: Brief Setup</h2>
            </div>

            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">Sub-stage</span>
              {(['LOBBY', 'BRIEFING', 'MODEL_PREPARING'] as SessionStage[]).map((stage) => (
                <span
                  key={stage}
                  className={`rounded-full px-2.5 py-1 font-semibold ${
                    backendStage === stage ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'
                  }`}
                >
                  {stage}
                </span>
              ))}
            </div>

            <textarea
              value={designGoal}
              onChange={(event) => onDesignGoalChange(event.target.value)}
              placeholder="Example: Winter-themed coating, blue-white palette, snowflake element, speed feeling."
              className="h-40 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:bg-white"
              disabled={!isHost}
            />
            <div className="mt-4 flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">Parse theme, colors, style keywords and constraints.</p>
              <button
                type="button"
                onClick={onParseBrief}
                disabled={!isHost || designGoal.trim().length === 0}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Bot size={14} />
                Parse Brief
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <Sparkles size={18} className="text-blue-600" />
              <h3 className="text-sm font-semibold text-slate-800">Structured Brief</h3>
            </div>
            {!brief ? (
              <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500">
                Brief has not been generated yet.
              </p>
            ) : (
              <div className="grid gap-3 text-sm text-slate-700 md:grid-cols-2">
                <InfoField label="Theme" value={brief.theme ?? '-'} />
                <InfoField label="Main Colors" value={brief.mainColors?.join(', ') ?? '-'} />
                <InfoField label="Accent Colors" value={brief.accentColors?.join(', ') ?? '-'} />
                <InfoField label="Style Keywords" value={brief.styleKeywords?.join(' / ') ?? '-'} />
                <InfoField label="Design Elements" value={brief.designElements?.join(' / ') ?? '-'} />
                <InfoField label="Product Category" value={brief.productCategory ?? '-'} />
                <div className="md:col-span-2">
                  <InfoField label="Constraints" value={brief.constraintsHint ?? '-'} />
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold text-slate-800">Product & Base Model Config</h3>

            <label className="mb-4 block text-xs font-semibold uppercase tracking-wider text-slate-500">
              Product Category
              <select
                value={productCategory}
                onChange={(event) => onProductCategoryChange(event.target.value as ProductCategory)}
                className="mt-2 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400 focus:bg-white"
                disabled={!isHost}
              >
                {categoryOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="mb-4 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Base Model Source</p>
              {sourceOptions.map((option) => {
                const optionDisabled = option.value !== 'upload' || !isHost;
                const isSelected = modelSource === option.value;
                return (
                <label
                  key={option.value}
                  className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${
                    optionDisabled
                      ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                      : 'cursor-pointer border-slate-200 bg-slate-50 text-slate-700'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      checked={isSelected}
                      onChange={() => onModelSourceChange(option.value)}
                      disabled={optionDisabled}
                    />
                    {option.icon}
                    {option.label}
                  </div>
                  {optionDisabled && option.value !== 'upload' ? (
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Coming Soon</span>
                  ) : isSelected ? (
                    <span className="text-xs font-semibold text-blue-600">Selected</span>
                  ) : null}
                </label>
                );
              })}
            </div>

            {modelSource === 'upload' ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="mb-2 text-xs text-slate-500">Supported: GLB / GLTF</p>
                <input
                  type="file"
                  accept=".glb,.gltf"
                  className="w-full text-xs text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-blue-600 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-white hover:file:bg-blue-700"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] ?? null;
                    onUploadFileSelected(selected);
                    if (selected?.name) {
                      updateProfile('uploaded_file_name', selected.name);
                    }
                  }}
                  disabled={!isHost}
                />
              </div>
            ) : null}

            <div
              className={`mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 ${
                showTaskPanel ? '' : 'hidden'
              }`}
            >
              <div className="flex items-center justify-between">
                <span>Model Task</span>
                <span className="font-semibold uppercase">{modelTaskStatus ?? 'idle'}</span>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-slate-500">
                <span>pipeline_stage: {modelPipelineStage ?? '-'}</span>
                <span>{modelProgressMessage ?? 'Waiting for model task'}</span>
              </div>
              <div className="mt-2 h-2 rounded-full bg-slate-200">
                <div className="h-full rounded-full bg-blue-600" style={{ width: `${safeTaskProgress}%` }} />
              </div>
              <p className="mt-1 text-right text-[11px]">{safeTaskProgress}%</p>
            </div>

            <div className="mt-4">
              <button
                type="button"
                onClick={onLockBaseModel}
                disabled={!isHost || !baseModel || baseModelLocked || preparingBaseModel}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Lock size={14} />
                Lock Base Model
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <ModelPreviewPanel
              modelUrl={baseModel?.modelUrl ?? null}
              title="Uploaded Model Preview"
              subtitle={uploadCardSubtitle}
              loading={preparingBaseModel}
            />

            <div className={`mt-4 space-y-2 text-sm text-slate-700 ${hasBaseModel ? '' : 'hidden'}`}>
              <div className="grid gap-3 md:grid-cols-2">
                <InfoField label="base_model_id" value={baseModelIdText} />
                <InfoField label="Source" value={baseModelSourceText} />
                <InfoField label="Precision" value={baseModelPrecisionText} />
                <InfoField label="License" value={baseModelLicenseText} />
                <InfoField
                  label="Surface Area"
                  value={baseModelSurfaceArea === null ? '-' : `${baseModelSurfaceArea.toFixed(2)} m^2`}
                />
                <InfoField
                  label="UV Pixels"
                  value={baseModelUvPixels === null ? '-' : String(Math.round(baseModelUvPixels))}
                />
                <InfoField label="UV Source" value={inspection?.uvSource ?? '-'} />
                <InfoField label="Mesh Count" value={inspection?.meshCount ? String(inspection.meshCount) : '-'} />
                <InfoField
                  label="Material Count"
                  value={inspection?.materialCount ? String(inspection.materialCount) : '-'}
                />
                <InfoField
                  label="BBox (m)"
                  value={inspection?.bboxM?.length ? inspection.bboxM.map((value) => value.toFixed(3)).join(' x ') : '-'}
                />
              </div>

              <div className="pt-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 ${
                    baseModelLocked ? '' : 'hidden'
                  }`}
                >
                  Locked, ready to enter DESIGNING
                </span>
                <span
                  className={`inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700 ${
                    baseModelLocked || !hasBaseModel ? 'hidden' : ''
                  }`}
                >
                  Uploaded and prepared, waiting for host lock
                </span>
              </div>

              {inspection?.warnings?.length ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  {inspection.warnings.join(' ')}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

const InfoField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
    <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
    <p className="text-sm text-slate-700">{value}</p>
  </div>
);

export default Stage1PlanningView;

