import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight, FileText, ImagePlus, LoaderCircle, Sparkles, X } from 'lucide-react';
import type { BaseModelMeta, DesignBrief, TexturePlanState } from '../types/design.ts';

interface TexturePlanningSidebarProps {
  token: string | null;
  sessionId: number | null;
  brief: DesignBrief | null;
  baseModel: BaseModelMeta | null;
  texturePlan: TexturePlanState | null;
  loading: boolean;
  generating: boolean;
  saving: boolean;
  imageAnalyzing: boolean;
  onAnalyzeReferenceImage: (file: File) => Promise<void>;
  onGenerateModelTextures: (payload: {
    sourceText: string;
    documentFile: File | null;
    referenceImageFile: File | null;
    selectedImageKeywords: string[];
  }) => Promise<boolean>;
  onUpdateSelectedImageKeywords: (keywords: string[]) => Promise<void>;
  onRemoveDocument: () => Promise<void>;
  onRemoveImage: () => Promise<void>;
}

const PANEL = 'rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 transition-all duration-300';

const dedupeKeywords = (keywords: string[]): string[] => Array.from(new Set(keywords.filter((item) => item.trim().length > 0)));
const SOURCE_LABELS: Record<string, string> = {
  upload: '上传模型',
  library: '模型库',
  generated: '生成模型',
};
const PRECISION_LABELS: Record<string, string> = {
  authoritative: '精确',
  standard: '标准',
  approximate: '近似',
};

const buildBriefTags = (brief: DesignBrief | null, baseModel: BaseModelMeta | null, texturePlan: TexturePlanState | null): string[] => {
  const tags: string[] = [];
  if (brief?.why?.coreExperienceIntent) {
    tags.push(`目标: ${brief.why.coreExperienceIntent}`);
  }
  if (brief?.theme) {
    tags.push(`主题: ${brief.theme}`);
  }
  if (brief?.what?.colorTendency) {
    tags.push(brief.what.colorTendency);
  }
  if (brief?.what?.visualStyleKeywords?.length) {
    tags.push(...brief.what.visualStyleKeywords.slice(0, 3));
  } else if (brief?.styleKeywords?.length) {
    tags.push(...brief.styleKeywords.slice(0, 3));
  }
  if (brief?.what?.referenceImagery?.length) {
    tags.push(...brief.what.referenceImagery.slice(0, 2));
  }
  if (brief?.softDirections?.length) {
    tags.push(...brief.softDirections.slice(0, 2));
  }
  if (brief?.mainColors?.length) {
    tags.push(...brief.mainColors.slice(0, 2));
  }
  if (texturePlan?.briefKeywords?.design_elements?.length) {
    tags.push(...texturePlan.briefKeywords.design_elements.slice(0, 4));
  }
  if (baseModel) {
    tags.push(SOURCE_LABELS[baseModel.sourceType] ?? baseModel.sourceType);
    tags.push(PRECISION_LABELS[baseModel.precisionLevel] ?? baseModel.precisionLevel);
  }
  return dedupeKeywords(tags).slice(0, 10);
};

const StaticChip: React.FC<{ label: string }> = ({ label }) => (
  <span className="rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500">
    {label}
  </span>
);

const ToggleChip: React.FC<{ label: string; selected: boolean; tone: 'emerald' | 'amber'; onClick: () => void }> = ({
  label,
  selected,
  tone,
  onClick,
}) => {
  const selectedClass =
    tone === 'emerald'
      ? 'border-emerald-300 bg-emerald-100/80 text-emerald-800 shadow-[inset_0_1px_2px_rgba(16,185,129,0.1)]'
      : 'border-amber-300 bg-amber-100/80 text-amber-800 shadow-[inset_0_1px_2px_rgba(245,158,11,0.1)]';
  const idleClass = 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:border-slate-300 shadow-sm';
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-[11px] font-medium transition-all duration-300 ease-out active:scale-95 ${selected ? selectedClass : idleClass}`}
    >
      {label}
    </button>
  );
};

const UploadBadge: React.FC<{
  label: string;
  onRemove: () => void;
}> = ({ label, onRemove }) => (
  <span className="inline-flex max-w-full items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600">
    <span className="truncate">{label}</span>
    <button type="button" onClick={onRemove} className="rounded-full p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700">
      <X size={11} />
    </button>
  </span>
);

const TexturePlanningSidebar: React.FC<TexturePlanningSidebarProps> = ({
  token,
  sessionId,
  brief,
  baseModel,
  texturePlan,
  loading,
  generating,
  saving,
  imageAnalyzing,
  onAnalyzeReferenceImage,
  onGenerateModelTextures,
  onUpdateSelectedImageKeywords,
  onRemoveDocument,
  onRemoveImage,
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const [briefPanelOpen, setBriefPanelOpen] = useState(false);
  const [sourceText, setSourceText] = useState('');
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [imagePanelOpen, setImagePanelOpen] = useState(false);

  const briefTags = useMemo(() => buildBriefTags(brief, baseModel, texturePlan), [baseModel, brief, texturePlan]);
  const contentKeywords = texturePlan?.imageContentKeywords ?? [];
  const styleKeywords = texturePlan?.imageStyleKeywords ?? [];
  const selectedImageKeywords = texturePlan?.selectedImageKeywords ?? [];
  const allImageKeywords = useMemo(() => dedupeKeywords([...contentKeywords, ...styleKeywords]), [contentKeywords, styleKeywords]);

  useEffect(() => {
    setSourceText(texturePlan?.sourceText ?? '');
  }, [texturePlan?.sourceText]);

  const currentDocumentLabel = documentFile?.name ?? texturePlan?.documentName ?? '';
  const currentImageLabel = referenceImageFile?.name ?? texturePlan?.imageName ?? '';
  const canGenerate = Boolean(token) && Boolean(sessionId) && (sourceText.trim().length > 0 || Boolean(documentFile) || Boolean(referenceImageFile) || Boolean(currentImageLabel));

  const handleToggleKeyword = (keyword: string) => {
    const nextKeywords = selectedImageKeywords.includes(keyword)
      ? selectedImageKeywords.filter((item) => item !== keyword)
      : [...selectedImageKeywords, keyword];
    void onUpdateSelectedImageKeywords(nextKeywords);
  };

  const handleRemoveDocumentClick = () => {
    setDocumentFile(null);
    void onRemoveDocument();
  };

  const handleRemoveImageClick = () => {
    setReferenceImageFile(null);
    void onRemoveImage();
  };

  return (
    <aside
      className={`relative shrink-0 border-r border-slate-200 bg-slate-50 transition-all duration-300 ${
        isOpen ? 'w-[24rem]' : 'w-0'
      }`}
    >
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        className="absolute -right-3 top-1/2 z-30 flex h-12 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition hover:text-slate-700"
      >
        {isOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
      </button>

      <div className={`flex h-full flex-col overflow-hidden ${isOpen ? 'opacity-100' : 'opacity-0'}`}>
        <div className="border-b border-slate-200 bg-white px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-blue-600 p-2 text-white">
                <Sparkles size={15} />
              </div>
              <div>
                <p className="text-[13px] font-semibold tracking-[0.16em] text-slate-800">纹理智能体</p>
              </div>
            </div>
            <div className="flex h-4 w-4 items-center justify-center">
              {loading ? <LoaderCircle size={14} className="animate-spin text-slate-400" /> : null}
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          <section className={PANEL}>
            <div 
              className="flex items-center justify-between cursor-pointer"
              onClick={() => setBriefPanelOpen((prev) => !prev)}
            >
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold tracking-tight text-slate-800">需求摘要</p>
                <div className="flex h-4 w-4 items-center justify-center">
                  {briefPanelOpen ? <ChevronDown size={14} className="text-slate-400" /> : <ChevronRight size={14} className="text-slate-400" />}
                </div>
              </div>
              <div className="flex min-w-[50px] justify-end">
                {saving ? <span className="text-[10px] text-slate-400">保存中...</span> : null}
              </div>
            </div>
            {briefPanelOpen ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {briefTags.length === 0 ? <span className="text-[11px] text-slate-400">暂无关键词。</span> : null}
                {briefTags.map((tag) => (
                  <StaticChip key={tag} label={tag} />
                ))}
              </div>
            ) : null}
          </section>

          <section className={PANEL}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold tracking-tight text-slate-800">输入</p>
              </div>
              <div className="flex max-w-[52%] flex-wrap justify-end gap-2">
                {currentDocumentLabel ? <UploadBadge label={currentDocumentLabel} onRemove={handleRemoveDocumentClick} /> : null}
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition hover:border-blue-300 hover:text-blue-700">
                  <FileText size={13} />
                  文档
                  <input
                    type="file"
                    accept=".txt,.md,.pdf,.docx"
                    className="hidden"
                    onChange={(event) => {
                      setDocumentFile(event.target.files?.[0] ?? null);
                      event.target.value = '';
                    }}
                  />
                </label>
              </div>
            </div>

            <textarea
              value={sourceText}
              onChange={(event) => setSourceText(event.target.value)}
              placeholder="输入纹理方向、限制条件、材料、品牌线索..."
              className="mt-3 min-h-[128px] w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition-all duration-300 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:ring-4 focus:ring-blue-500/10 focus:shadow-sm"
            />
          </section>

          <section className={PANEL}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold tracking-tight text-slate-800">参考图</p>
              </div>
              <div className="flex max-w-[56%] flex-wrap justify-end gap-2">
                {currentImageLabel ? <UploadBadge label={currentImageLabel} onRemove={handleRemoveImageClick} /> : null}
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition hover:border-blue-300 hover:text-blue-700">
                  <ImagePlus size={13} />
                  上传
                  <input
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp,.gif"
                    className="hidden"
                    onChange={(event) => {
                      setReferenceImageFile(event.target.files?.[0] ?? null);
                      setImagePanelOpen(true);
                      event.target.value = '';
                    }}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setImagePanelOpen((previous) => !previous)}
                  className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                >
                  {imagePanelOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
              </div>
            </div>

            {imagePanelOpen ? (
              <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-3 transition-colors duration-300 hover:border-blue-300 hover:bg-blue-50/30">
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {referenceImageFile ? (
                    <button
                      type="button"
                      onClick={() => {
                        void onAnalyzeReferenceImage(referenceImageFile);
                      }}
                      disabled={imageAnalyzing}
                      className="inline-flex items-center gap-1 rounded-full bg-blue-600 px-3 py-1.5 text-[11px] font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {imageAnalyzing ? <LoaderCircle size={12} className="animate-spin" /> : <Sparkles size={12} />}
                      分析
                    </button>
                  ) : null}
                </div>

                {allImageKeywords.length ? (
                  <div className="mt-3 space-y-3">
                    {contentKeywords.length ? (
                      <div>
                        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">内容</p>
                        <div className="flex flex-wrap gap-2">
                          {contentKeywords.map((keyword) => (
                            <ToggleChip
                              key={`content-${keyword}`}
                              label={keyword}
                              tone="emerald"
                              selected={selectedImageKeywords.includes(keyword)}
                              onClick={() => handleToggleKeyword(keyword)}
                            />
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {styleKeywords.length ? (
                      <div>
                        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">风格</p>
                        <div className="flex flex-wrap gap-2">
                          {styleKeywords.map((keyword) => (
                            <ToggleChip
                              key={`style-${keyword}`}
                              label={keyword}
                              tone="amber"
                              selected={selectedImageKeywords.includes(keyword)}
                              onClick={() => handleToggleKeyword(keyword)}
                            />
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          <button
            type="button"
            onClick={() => {
              void (async () => {
                const succeeded = await onGenerateModelTextures({
                  sourceText,
                  documentFile,
                  referenceImageFile,
                  selectedImageKeywords,
                });
                if (succeeded) {
                  setIsOpen(false);
                }
              })();
            }}
            disabled={!canGenerate || generating}
            className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {generating ? <LoaderCircle size={15} className="animate-spin" /> : <Sparkles size={15} />}
            生成
          </button>
        </div>
      </div>
    </aside>
  );
};

export default TexturePlanningSidebar;
