import React from 'react';
import {
  FileOutput,
  HardHat,
  Lock,
  Plus,
  Settings2,
  Sparkles,
  Trash2,
  Users,
  Workflow,
  X,
} from 'lucide-react';
import type {
  MeetingSettings,
  MeetingSettingsPermissions,
  MeetingSettingsSection,
  MeetingSettingsSectionId,
  ReviewPersonaRoleConfig,
} from '../types/meeting.ts';

interface MeetingSettingsModalProps {
  open: boolean;
  loading: boolean;
  saving: boolean;
  settings: MeetingSettings | null;
  permissions: MeetingSettingsPermissions | null;
  sections: MeetingSettingsSection[];
  activeSectionId: MeetingSettingsSectionId;
  onSelectSection: (sectionId: MeetingSettingsSectionId) => void;
  onClose: () => void;
  onRolesChange: (roles: ReviewPersonaRoleConfig[]) => void;
  onSave: () => void;
  onRestoreDefaults: () => void;
}

const SECTION_ICONS: Record<MeetingSettingsSectionId, React.ReactNode> = {
  review_roles: <Users size={15} />,
  passenger_evaluation: <Users size={15} />,
  engineering_evaluation: <HardHat size={15} />,
  collaboration_rules: <Sparkles size={15} />,
  meeting_workflow: <Workflow size={15} />,
  export_preferences: <FileOutput size={15} />,
};

const SECTION_LABELS: Record<MeetingSettingsSectionId, string> = {
  review_roles: '评审角色',
  passenger_evaluation: '乘客评审',
  engineering_evaluation: '工程评审',
  collaboration_rules: '协作规则',
  meeting_workflow: '会议流程',
  export_preferences: '导出偏好',
};

const getSectionLabel = (section: MeetingSettingsSection | null | undefined): string => {
  if (!section) {
    return '设置';
  }
  return SECTION_LABELS[section.id] ?? section.label;
};

const splitLines = (value: string): string[] =>
  value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);

const joinLines = (value: string[]): string => value.join('\n');

const formatListForPrompt = (label: string, items: string[]): string | null => {
  const normalized = items.map((item) => item.trim()).filter(Boolean);
  return normalized.length > 0 ? `${label}：${normalized.join('、')}。` : null;
};

const roleTypeLabel = (type: ReviewPersonaRoleConfig['type']): string => {
  if (type === 'engineering') {
    return '工程类评审';
  }
  if (type === 'passenger') {
    return '乘客类评审';
  }
  return '自定义视角评审';
};

const buildRolePrompt = (role: ReviewPersonaRoleConfig): string => {
  const lines = [
    `你将扮演“${role.displayName || '自定义评审角色'}”。`,
    `角色类型：${roleTypeLabel(role.type)}。`,
    `角色身份与特征：${role.identitySummary || '根据该角色立场评估方案。'}`,
    '评价标准 / Skill 指令：',
    formatListForPrompt('重点关注', role.focusPoints),
    formatListForPrompt('偏好倾向', role.preferenceTags),
    formatListForPrompt('反感或警惕', role.dislikeTags),
    formatListForPrompt('优先判断标准', role.priorityTags),
    formatListForPrompt('风险关注', role.riskFocus),
    '判断时优先依据该团队或角色的标准、偏好、限制、风险关注和证据要求。',
    '请从该角色的真实立场出发，围绕方案是否符合其利益、期待、限制和决策习惯给出具体反馈。',
    '这段指令只用于校准评审立场和判断标准，不要求改变系统规定的输出格式。',
  ];
  return lines.filter((line): line is string => Boolean(line)).join('\n');
};

const createRole = (type: ReviewPersonaRoleConfig['type']): ReviewPersonaRoleConfig => {
  const suffix = `${type}_${Date.now().toString(36)}`;
  if (type === 'custom') {
    const role: ReviewPersonaRoleConfig = {
      id: suffix,
      type,
      enabled: true,
      displayName: '自定义评审角色',
      identitySummary: '例如品牌方、老板、甲方或运营方，请描述该角色的立场、目标和判断习惯。',
      focusPoints: ['角色关注点', '方案匹配度', '风险与建议'],
      preferenceTags: ['符合角色利益'],
      dislikeTags: ['不符合项目目标'],
      priorityTags: ['决策优先级'],
      riskFocus: ['沟通风险'],
      rolePrompt: '',
    };
    return {
      ...role,
      rolePrompt: buildRolePrompt(role),
    };
  }
  if (type === 'engineering') {
    const role: ReviewPersonaRoleConfig = {
      id: suffix,
      type,
      enabled: true,
      displayName: '新工程评审',
      identitySummary: '从制造、维护、成本和风险角度评估方案。',
      focusPoints: ['工艺可行性', '成本', '维护'],
      preferenceTags: [],
      dislikeTags: [],
      priorityTags: ['工艺稳定', '易维护'],
      riskFocus: ['色差风险', '遮蔽工作量'],
      rolePrompt: null,
    };
    return {
      ...role,
      rolePrompt: buildRolePrompt(role),
    };
  }
  const role: ReviewPersonaRoleConfig = {
    id: suffix,
    type,
    enabled: true,
    displayName: '新乘客评审',
    identitySummary: '从乘客第一印象、信任感和乘坐意愿评估方案。',
    focusPoints: ['第一印象', '舒适感', '信任感'],
    preferenceTags: ['清爽', '现代'],
    dislikeTags: ['杂乱', '廉价感'],
    priorityTags: [],
    riskFocus: [],
    rolePrompt: null,
  };
  return {
    ...role,
    rolePrompt: buildRolePrompt(role),
  };
};

const SectionButton: React.FC<{
  section: MeetingSettingsSection;
  active: boolean;
  onSelect: () => void;
}> = ({ section, active, onSelect }) => (
  <button
    type="button"
    onClick={section.enabled ? onSelect : undefined}
    disabled={!section.enabled}
    className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
      active
        ? 'border-blue-200 bg-blue-50 text-blue-700'
        : section.enabled
          ? 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
          : 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400'
    }`}
  >
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          {SECTION_ICONS[section.id]}
        </span>
        <p className="text-sm font-semibold">{getSectionLabel(section)}</p>
      </div>
      {!section.enabled && section.badge ? (
        <span className="shrink-0 rounded-full bg-slate-200 px-2 py-1 text-[10px] font-semibold text-slate-500">
          {section.badge}
        </span>
      ) : null}
    </div>
  </button>
);

const TextField: React.FC<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  multiline?: boolean;
}> = ({ label, value, onChange, disabled = false, multiline = false }) => (
  <label className="block">
    <span className="text-[11px] font-semibold tracking-[0.08em] text-slate-400">{label}</span>
    {multiline ? (
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        rows={3}
        className="mt-2 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-blue-400 disabled:cursor-not-allowed disabled:bg-slate-50"
      />
    ) : (
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="mt-2 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 disabled:cursor-not-allowed disabled:bg-slate-50"
      />
    )}
  </label>
);

const MeetingSettingsModal: React.FC<MeetingSettingsModalProps> = ({
  open,
  loading,
  saving,
  settings,
  permissions,
  sections,
  activeSectionId,
  onSelectSection,
  onClose,
  onRolesChange,
  onSave,
  onRestoreDefaults,
}) => {
  if (!open) {
    return null;
  }

  const canEdit = Boolean(permissions?.canEdit);
  const roles = settings?.reviewPersonas.roles ?? [];
  const activeSection = sections.find((item) => item.id === activeSectionId) ?? sections[0] ?? null;

  const updateRole = (roleId: string, patch: Partial<ReviewPersonaRoleConfig>) => {
    const currentRole = roles.find((role) => role.id === roleId);
    if (currentRole && patch.enabled === false) {
      const enabledCount = roles.filter((role) => role.enabled).length;
      if (currentRole.enabled && enabledCount <= 1) {
        return;
      }
    }
    onRolesChange(roles.map((role) => (role.id === roleId ? { ...role, ...patch } : role)));
  };

  const deleteRole = (roleId: string) => {
    const role = roles.find((item) => item.id === roleId);
    if (!role) {
      return;
    }
    const enabledCount = roles.filter((item) => item.enabled).length;
    if (role.enabled && enabledCount <= 1) {
      return;
    }
    onRolesChange(roles.filter((item) => item.id !== roleId));
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/35 px-4 py-6 backdrop-blur-sm">
      <div className="flex h-full max-h-[82vh] w-full max-w-6xl overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-2xl">
        <aside className="flex w-[320px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/70 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">设置</p>
              <h2 className="mt-2 text-xl font-bold tracking-tight text-slate-900">评审设置</h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-100"
              title="关闭设置"
            >
              <X size={16} />
            </button>
          </div>

          <div className="mt-5 space-y-2 overflow-y-auto pr-1">
            {sections.map((section) => (
              <SectionButton
                key={section.id}
                section={section}
                active={section.id === activeSectionId}
                onSelect={() => onSelectSection(section.id)}
              />
            ))}
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="border-b border-slate-200 px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-blue-50 text-blue-600">
                  <Settings2 size={15} />
                </span>
                <h3 className="text-lg font-semibold text-slate-900">{getSectionLabel(activeSection)}</h3>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-semibold text-slate-500">
                  修订 {settings?.revision ?? 1}
                </span>
                {canEdit ? (
                  <span className="rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-600">
                    可编辑
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-700">
                    <Lock size={11} />
                    只读
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
            {loading || !settings ? (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">加载中...</div>
            ) : activeSectionId === 'review_roles' ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm text-slate-500">可按项目需要增减评审角色，至少保留一个启用角色。</p>
                  {canEdit ? (
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => onRolesChange([...roles, createRole('passenger')])}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                      >
                        <Plus size={13} />
                        添加乘客角色
                      </button>
                      <button
                        type="button"
                        onClick={() => onRolesChange([...roles, createRole('engineering')])}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                      >
                        <Plus size={13} />
                        添加工程角色
                      </button>
                      <button
                        type="button"
                        onClick={() => onRolesChange([...roles, createRole('custom')])}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-fuchsia-100 bg-fuchsia-50 px-3 py-2 text-xs font-semibold text-fuchsia-700 transition hover:bg-fuchsia-100"
                      >
                        <Plus size={13} />
                        添加自定义角色
                      </button>
                    </div>
                  ) : null}
                </div>

                {roles.map((role) => {
                  const canDeleteRole = canEdit && (!role.enabled || roles.filter((item) => item.enabled).length > 1);
                  return (
                    <div key={role.id} className="rounded-[1.5rem] border border-slate-200 bg-slate-50/60 p-4">
                      <div className="mb-4 flex items-start justify-between gap-3">
                        <div>
                          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                            role.type === 'custom'
                              ? 'bg-fuchsia-50 text-fuchsia-700'
                              : role.type === 'engineering'
                                ? 'bg-amber-50 text-amber-700'
                                : 'bg-blue-50 text-blue-700'
                          }`}>
                            {role.type === 'custom' ? '自定义' : role.type === 'engineering' ? '工程类' : '乘客类'}
                          </span>
                          <p className="mt-2 text-sm font-semibold text-slate-800">{role.displayName}</p>
                        </div>
                        {canEdit ? (
                          <div className="flex items-center gap-2">
                            <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500">
                              <input
                                type="checkbox"
                                checked={role.enabled}
                                onChange={(event) => updateRole(role.id, { enabled: event.target.checked })}
                              />
                              启用
                            </label>
                            <button
                              type="button"
                              onClick={() => deleteRole(role.id)}
                              disabled={!canDeleteRole}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-rose-100 bg-white text-rose-500 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
                              title="删除角色"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        ) : null}
                      </div>

                      <div className="grid gap-4 md:grid-cols-2">
                        <TextField
                          label="角色名称"
                          value={role.displayName}
                          onChange={(value) => updateRole(role.id, { displayName: value })}
                          disabled={!canEdit}
                        />
                        <TextField
                          label="关注点（一行一个）"
                          value={joinLines(role.focusPoints)}
                          onChange={(value) => updateRole(role.id, { focusPoints: splitLines(value) })}
                          disabled={!canEdit}
                          multiline
                        />
                        <div className="md:col-span-2">
                          <TextField
                            label="角色特征"
                            value={role.identitySummary}
                            onChange={(value) => updateRole(role.id, { identitySummary: value })}
                            disabled={!canEdit}
                            multiline
                          />
                        </div>
                        <div className="md:col-span-2">
                          <div className="mb-2 flex items-center justify-between gap-3">
                            <span className="text-[11px] font-semibold tracking-[0.08em] text-slate-400">
                              评价标准 / Skill 指令（可编辑）
                            </span>
                            {canEdit ? (
                              <button
                                type="button"
                                onClick={() => updateRole(role.id, { rolePrompt: buildRolePrompt(role) })}
                                className="rounded-lg border border-blue-100 bg-white px-2.5 py-1 text-[11px] font-semibold text-blue-700 transition hover:bg-blue-50"
                              >
                                自动生成
                              </button>
                            ) : null}
                          </div>
                          <textarea
                            value={role.rolePrompt ?? buildRolePrompt(role)}
                            onChange={(event) => updateRole(role.id, { rolePrompt: event.target.value })}
                            disabled={!canEdit}
                            rows={6}
                            className="w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-blue-400 disabled:cursor-not-allowed disabled:bg-slate-50"
                          />
                        </div>
                        {role.type === 'engineering' ? (
                          <>
                            <TextField
                              label="工程优先级（一行一个）"
                              value={joinLines(role.priorityTags)}
                              onChange={(value) => updateRole(role.id, { priorityTags: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                            <TextField
                              label="风险关注（一行一个）"
                              value={joinLines(role.riskFocus)}
                              onChange={(value) => updateRole(role.id, { riskFocus: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                          </>
                        ) : (
                          <>
                            <TextField
                              label="偏好标签（一行一个）"
                              value={joinLines(role.preferenceTags)}
                              onChange={(value) => updateRole(role.id, { preferenceTags: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                            <TextField
                              label="反感标签（一行一个）"
                              value={joinLines(role.dislikeTags)}
                              onChange={(value) => updateRole(role.id, { dislikeTags: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                          </>
                        )}
                        {role.type === 'custom' ? (
                          <>
                            <TextField
                              label="优先标准（一行一个）"
                              value={joinLines(role.priorityTags)}
                              onChange={(value) => updateRole(role.id, { priorityTags: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                            <TextField
                              label="风险关注（一行一个）"
                              value={joinLines(role.riskFocus)}
                              onChange={(value) => updateRole(role.id, { riskFocus: splitLines(value) })}
                              disabled={!canEdit}
                              multiline
                            />
                          </>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center">
                <div className="max-w-md rounded-[1.75rem] border border-dashed border-slate-200 bg-slate-50 px-6 py-8 text-center">
                  <p className="text-sm font-semibold text-slate-700">该设置项即将开放。</p>
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-slate-200 bg-slate-50/70 px-6 py-5">
            <div className="flex items-center justify-end gap-2">
              {canEdit ? (
                <>
                  <button
                    type="button"
                    onClick={onRestoreDefaults}
                    disabled={saving}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                  >
                    恢复默认
                  </button>
                  <button
                    type="button"
                    onClick={onSave}
                    disabled={saving}
                    className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:opacity-50"
                  >
                    {saving ? '保存中...' : '保存'}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-slate-800"
                >
                  关闭
                </button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default MeetingSettingsModal;
