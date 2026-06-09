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
  { value: 'high_speed_train', label: '高速列车' },
  { value: 'intercity_train', label: '城际列车' },
  { value: 'metro_vehicle', label: '地铁车辆' },
  { value: 'automobile', label: '汽车' },
  { value: 'home_appliance', label: '家电' },
  { value: 'industrial_other', label: '其他工业产品' },
];

const sourceOptions: Array<{ value: BaseModelSource; label: string; icon: React.ReactNode }> = [
  { value: 'upload', label: '上传模型', icon: <CloudUpload size={14} /> },
  { value: 'library', label: '模型库选择', icon: <Database size={14} /> },
  { value: 'generate', label: '自动生成近似模型', icon: <Wand2 size={14} /> },
];

const precisionTextMap = {
  authoritative: '精确',
  standard: '标准',
  approximate: '近似',
} as const;

const sourceTagMap = {
  upload: '上传',
  library: '模型库',
  generate: '生成',
} as const;

const taskStatusLabel = (status: string | null): string => {
  if (!status) {
    return '空闲';
  }
  const labels: Record<string, string> = {
    idle: '空闲',
    uploading: '上传中',
    queued: '排队中',
    processing: '处理中',
    ready: '已就绪',
    failed: '失败',
  };
  return labels[status] ?? status;
};

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

const toText = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

const toList = (value: unknown, maxItems = 8): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  const picked: string[] = [];
  for (const item of value) {
    const text = toText(item);
    if (!text || picked.includes(text)) {
      continue;
    }
    picked.push(text);
    if (picked.length >= maxItems) {
      break;
    }
  }
  return picked;
};

const mergeLists = (...groups: string[][]): string[] => {
  const merged: string[] = [];
  for (const group of groups) {
    for (const item of group) {
      if (!item || merged.includes(item)) {
        continue;
      }
      merged.push(item);
    }
  }
  return merged;
};

const categoryLabel = (value: ProductCategory): string =>
  categoryOptions.find((option) => option.value === value)?.label ?? value;

const buildIntentSummary = (brief: DesignBrief) => {
  const whyCore = toText(brief.why?.coreExperienceIntent) || toText(brief.theme);
  const whyCulture = toText(brief.why?.culturalBrandPositioning) || categoryLabel(brief.productCategory);

  const whatColor = toText(brief.what?.colorTendency) || toList(brief.mainColors, 3).join(' / ');
  const whatKeywords = toList(brief.what?.visualStyleKeywords, 5).length
    ? toList(brief.what?.visualStyleKeywords, 5)
    : toList(brief.styleKeywords, 5);
  const referenceImagery = toList(brief.what?.referenceImagery, 4).length
    ? toList(brief.what?.referenceImagery, 4)
    : toList(brief.designElements, 4);

  const craftTechConstraints = toList(brief.how?.craftTechConstraints, 5);
  const regulatoryConstraints = toList(brief.how?.regulatoryConstraints, 5);
  const fallbackConstraint = toText(brief.constraintsHint);

  const lockedItems = toList(brief.lockedItems, 5);
  const softDirections = toList(brief.softDirections, 5);
  const openNarrative = toText(brief.openNarrative) || toText(brief.theme);

  return {
    whyCore,
    whyCulture,
    whatColor,
    whatKeywords,
    referenceImagery,
    craftTechConstraints: craftTechConstraints.length
      ? craftTechConstraints
      : (fallbackConstraint ? [fallbackConstraint] : []),
    regulatoryConstraints,
    openNarrative,
    lockedItems: lockedItems.length ? lockedItems : (fallbackConstraint ? [fallbackConstraint] : []),
    softDirections: softDirections.length ? softDirections : mergeLists(whatKeywords, referenceImagery).slice(0, 5),
    metadataTags: mergeLists(
      toList(brief.mainColors, 2),
      toList(brief.accentColors, 2),
      whatKeywords.slice(0, 2),
      referenceImagery.slice(0, 2),
    ).slice(0, 6),
  };
};

const Stage1PlanningView: React.FC<Stage1PlanningViewProps> = ({
  isHost,
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
  const intentSummary = brief ? buildIntentSummary(brief) : null;
  const intentProductCategoryLabel = brief ? categoryLabel(brief.productCategory) : categoryLabel(productCategory);
  const pendingIntentText = brief ? '-' : '待解析';
  const baseModelIdText = hasBaseModel ? String(baseModel?.baseModelId ?? '-') : '-';
  const baseModelSourceText = hasBaseModel
    ? (sourceTagMap[baseModel?.sourceType ?? 'library'] ?? String(baseModel?.sourceType ?? '-'))
    : '-';
  const baseModelPrecisionText = hasBaseModel
    ? (precisionTextMap[baseModel?.precisionLevel ?? 'standard'] ?? String(baseModel?.precisionLevel ?? '-'))
    : '-';
  const modelSourcePrecisionText = hasBaseModel ? `${baseModelSourceText} / ${baseModelPrecisionText}` : '-';
  const paintableAreaText = baseModelSurfaceArea === null ? '-' : `${baseModelSurfaceArea.toFixed(2)} m^2`;
  const uvMeshText = hasBaseModel
    ? `UV ${baseModelUvPixels === null ? '-' : Math.round(baseModelUvPixels)} / 网格 ${
        inspection?.meshCount ? inspection.meshCount : '-'
      }`
    : '-';
  const lockStatusText = baseModelLocked ? '已锁定' : (hasBaseModel ? '可锁定' : '未锁定状态');

  const updateProfile = (key: string, value: ProductProfileValue) => {
    onProductProfileChange({
      ...productProfile,
      [key]: value,
    });
  };

  return (
    <div className="flex-1 overflow-y-auto bg-slate-50">
      <div className="mx-auto w-full max-w-[1500px] p-6">
        <div className="grid gap-6 lg:grid-cols-[1.45fr_1fr]">
          <section className="space-y-6">
            {!isHost ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                仅主持人可操作。
              </div>
            ) : null}

          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <div className="mb-8 flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <FileText size={16} className="text-slate-400" />
                <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-slate-800">设计任务</h2>
              </div>
            </div>

            <textarea
              value={designGoal}
              onChange={(event) => onDesignGoalChange(event.target.value)}
              placeholder="请输入本次设计任务目标、风格方向和关键约束。"
              className="h-32 w-full resize-none rounded-xl border border-slate-200 bg-slate-50 p-4 text-[13px] leading-relaxed text-slate-700 outline-none transition focus:border-blue-400 focus:bg-white"
              disabled={!isHost}
            />
            <div className="mt-4 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={onParseBrief}
                disabled={!isHost || designGoal.trim().length === 0}
                className="inline-flex min-w-[132px] items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Bot size={14} />
                解析意图
              </button>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <div className="mb-6 flex items-center gap-2">
              <Sparkles size={16} className="text-blue-500" />
              <h3 className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">设计意图解析智能体</h3>
            </div>
            <div className="space-y-6 text-sm text-slate-700">
              <div className="min-h-[128px] rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <IntentMetaChip label={`品类：${intentProductCategoryLabel}`} />
                  {intentSummary?.whatColor ? <IntentMetaChip label={`色彩倾向：${intentSummary.whatColor}`} /> : null}
                  {!brief ? <IntentMetaChip label="待解析" /> : null}
                  {intentSummary?.metadataTags.map((tag) => (
                    <IntentMetaChip key={tag} label={tag} />
                  ))}
                </div>
                <div className="mt-4">
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">开放叙事</p>
                  <p className="mt-2 text-[14px] leading-6 text-slate-700">
                    {intentSummary?.openNarrative || pendingIntentText}
                  </p>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <IntentCard
                  title="设计意图"
                >
                  <IntentTextBlock label="核心体验意图" value={intentSummary?.whyCore || pendingIntentText} />
                  <IntentTextBlock label="文化 / 品牌定位" value={intentSummary?.whyCulture || pendingIntentText} />
                </IntentCard>

                <IntentCard
                  title="视觉方向"
                >
                  <IntentTextBlock label="色彩倾向" value={intentSummary?.whatColor || pendingIntentText} />
                  <IntentChipBlock
                    label="视觉风格关键词"
                    items={intentSummary?.whatKeywords ?? []}
                    emptyText={brief ? '暂未提取视觉风格关键词。' : pendingIntentText}
                  />
                  <IntentChipBlock
                    label="参考意象"
                    items={intentSummary?.referenceImagery ?? []}
                    emptyText={brief ? '暂未提取隐喻或意象参考。' : pendingIntentText}
                  />
                </IntentCard>

                <IntentCard
                  title="约束"
                >
                  <IntentListBlock
                    label="工艺 / 技术约束"
                    items={intentSummary?.craftTechConstraints ?? []}
                    emptyText={brief ? '暂未提取工艺或技术约束。' : pendingIntentText}
                  />
                  <IntentListBlock
                    label="规范约束"
                    items={intentSummary?.regulatoryConstraints ?? []}
                    emptyText={brief ? '暂未提取规范约束。' : pendingIntentText}
                  />
                </IntentCard>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <IntentListPanel
                  title="锁定项"
                  emptyText={brief ? '暂未提取锁定项。' : pendingIntentText}
                  items={intentSummary?.lockedItems ?? []}
                  tone="amber"
                />
                <IntentListPanel
                  title="柔性方向"
                  emptyText={brief ? '暂未提取柔性方向。' : pendingIntentText}
                  items={intentSummary?.softDirections ?? []}
                  tone="blue"
                />
              </div>
            </div>
          </div>
        </section>

          <section className="space-y-6">
            <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <h3 className="mb-6 text-sm font-bold tracking-tight text-slate-800">产品与基准模型配置</h3>
            <label className="mb-4 block text-xs font-semibold uppercase tracking-wider text-slate-500">
              产品类别
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
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">基准模型来源</p>
              {sourceOptions.map((option) => {
                const optionDisabled = option.value !== 'upload' || !isHost;
                const isSelected = modelSource === option.value;
                return (
                <label
                  key={option.value}
                  className={`flex min-h-[48px] items-center justify-between rounded-lg border px-3 py-2 text-sm ${
                    isSelected
                      ? 'border-blue-200 bg-blue-50 text-slate-700'
                      : optionDisabled
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
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">即将开放</span>
                  ) : isSelected ? (
                    <span className="text-xs font-semibold text-blue-600">已选择</span>
                  ) : null}
                </label>
                );
              })}
            </div>

            {modelSource === 'upload' ? (
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px]">
                <label
                  className={`flex min-h-[52px] items-center rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm font-medium text-slate-600 transition hover:bg-white ${
                    isHost ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'
                  }`}
                >
                  <CloudUpload size={14} className="mr-2 shrink-0 text-slate-400" />
                  <span className="truncate">{uploadedFileName ?? 'GLB / GLTF 文件上传入口'}</span>
                  <input
                    type="file"
                    accept=".glb,.gltf"
                    className="sr-only"
                    onChange={(event) => {
                      const selected = event.target.files?.[0] ?? null;
                      onUploadFileSelected(selected);
                      if (selected?.name) {
                        updateProfile('uploaded_file_name', selected.name);
                      }
                    }}
                    disabled={!isHost}
                  />
                </label>
                <button
                  type="button"
                  onClick={onLockBaseModel}
                  disabled={!isHost || !baseModel || baseModelLocked || preparingBaseModel}
                  className="inline-flex min-h-[52px] w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Lock size={14} />
                  锁定基准模型
                </button>
              </div>
            ) : null}

            <div
              className={`mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 ${
                showTaskPanel ? '' : 'hidden'
              }`}
            >
              <div className="flex items-center justify-between">
                <span>模型</span>
                <span className="font-semibold uppercase">{taskStatusLabel(modelTaskStatus)}</span>
              </div>
              <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-slate-500">
                <span>{modelPipelineStage ?? '-'}</span>
                <span>{modelProgressMessage ?? '等待中'}</span>
              </div>
              <div className="mt-2 h-2 rounded-full bg-slate-200">
                <div className="h-full rounded-full bg-blue-600" style={{ width: `${safeTaskProgress}%` }} />
              </div>
              <p className="mt-1 text-right text-[11px]">{safeTaskProgress}%</p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
            <ModelPreviewPanel
              modelUrl={baseModel?.modelUrl ?? null}
              title="基础模型预览"
              subtitle="GLB / GLTF / 处理状态"
              loading={preparingBaseModel}
              framed={false}
              previewClassName="relative mt-6 h-[320px] overflow-hidden rounded-xl border border-slate-200 bg-gradient-to-br from-slate-100 via-white to-blue-50"
            />

            <div className="mt-6 space-y-4 text-sm text-slate-700">
              <div className="grid gap-4 md:grid-cols-2">
                <InfoField label="base_model_id" value={baseModelIdText} />
                <InfoField label="来源 / 精度" value={modelSourcePrecisionText} />
                <InfoField label="可喷涂面积" value={paintableAreaText} />
                <InfoField label="UV 像素 / 网格信息" value={uvMeshText} />
              </div>

              <div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 ${
                    baseModelLocked ? '' : 'hidden'
                  }`}
                >
                  已锁定
                </span>
                <span
                  className={`inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700 ${
                    baseModelLocked || !hasBaseModel ? 'hidden' : ''
                  }`}
                >
                  可锁定
                </span>
                <span
                  className={`inline-flex items-center gap-1 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 ${
                    hasBaseModel ? 'hidden' : ''
                  }`}
                >
                  {lockStatusText}
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
    </div>
  );
};

const IntentMetaChip: React.FC<{ label: string }> = ({ label }) => (
  <span className="inline-flex items-center rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-medium text-slate-600 shadow-sm">
    {label}
  </span>
);

const IntentCard: React.FC<{
  title: string;
  children: React.ReactNode;
}> = ({ title, children }) => (
  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
    <div className="mt-4 space-y-4">{children}</div>
  </div>
);

const IntentTextBlock: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{label}</p>
    <p className="mt-1 text-[13px] leading-6 text-slate-700">{value}</p>
  </div>
);

const IntentChipBlock: React.FC<{ label: string; items: string[]; emptyText: string }> = ({ label, items, emptyText }) => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{label}</p>
    {items.length ? (
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            key={`${label}-${item}`}
            className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600"
          >
            {item}
          </span>
        ))}
      </div>
    ) : (
      <p className="mt-2 text-[12px] text-slate-400">{emptyText}</p>
    )}
  </div>
);

const IntentListBlock: React.FC<{ label: string; items: string[]; emptyText: string }> = ({ label, items, emptyText }) => (
  <div>
    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{label}</p>
    {items.length ? (
      <div className="mt-2 space-y-2">
        {items.map((item, index) => (
          <div
            key={`${label}-${index}`}
            className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] leading-5 text-slate-700"
          >
            {item}
          </div>
        ))}
      </div>
    ) : (
      <p className="mt-2 text-[12px] text-slate-400">{emptyText}</p>
    )}
  </div>
);

const IntentListPanel: React.FC<{
  title: string;
  items: string[];
  emptyText: string;
  tone: 'amber' | 'blue';
}> = ({ title, items, emptyText, tone }) => {
  const toneClass =
    tone === 'amber'
      ? 'border-amber-200 bg-amber-50/60'
      : 'border-blue-200 bg-blue-50/60';
  const badgeClass =
    tone === 'amber'
      ? 'bg-amber-600 text-white'
      : 'bg-blue-600 text-white';

  return (
    <div className={`rounded-2xl border p-4 shadow-sm ${toneClass}`}>
      <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
      {items.length ? (
        <div className="mt-4 space-y-2">
          {items.map((item, index) => (
            <div
              key={`${title}-${index}`}
              className="flex items-start gap-3 rounded-xl border border-white/70 bg-white/90 px-3 py-2.5 text-[13px] leading-5 text-slate-700 shadow-sm"
            >
              <span className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${badgeClass}`}>
                {index + 1}
              </span>
              <p>{item}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-[12px] text-slate-400">{emptyText}</p>
      )}
    </div>
  );
};

const InfoField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 shadow-sm transition-colors hover:bg-white">
    <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
    <p className="text-[13px] font-semibold text-slate-800">{value}</p>
  </div>
);

export default Stage1PlanningView;

