import React, { useMemo, useState } from 'react';
import { Bot, ChevronLeft, ChevronRight, Keyboard, Lock, MoreHorizontal, Users, View } from 'lucide-react';
import type { SessionMemberDirectoryEntry } from '../types/meeting.ts';

interface ParticipantSidebarProps {
  participants?: SessionMemberDirectoryEntry[];
  currentUserId?: number | null;
  onLiveSync?: (participant: SessionMemberDirectoryEntry) => void;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

const roleLabelMap: Record<SessionMemberDirectoryEntry['role'], string> = {
  host: '主持人',
  designer: '设计师',
  observer: '观察员',
};

const normalizeRoleLabel = (participant: SessionMemberDirectoryEntry): string => {
  const raw = participant.roleLabel?.trim();
  if (!raw) {
    return roleLabelMap[participant.role];
  }
  const labels: Record<string, string> = {
    Host: '主持人',
    Designer: '设计师',
    Observer: '观察员',
  };
  return labels[raw] ?? raw;
};

const palette = [
  'bg-blue-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-fuchsia-500',
  'bg-cyan-500',
  'bg-rose-500',
  'bg-violet-500',
  'bg-sky-500',
];

const ParticipantSidebarContent: React.FC<{
  participants: SessionMemberDirectoryEntry[];
  currentUserId?: number | null;
  onLiveSync?: (participant: SessionMemberDirectoryEntry) => void;
  onCollapse?: () => void;
  collapsible?: boolean;
}> = ({ participants, currentUserId, onLiveSync, onCollapse, collapsible = false }) => (
  <>
    <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-4">
      <div className="flex items-center gap-2">
        <Users size={14} className="text-slate-400" />
        <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">
          团队 ({participants.length})
        </span>
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
        >
          <MoreHorizontal size={14} />
        </button>
        {collapsible ? (
          <button
            type="button"
            onClick={onCollapse}
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label="收起成员面板"
          >
            <ChevronRight size={16} />
          </button>
        ) : null}
      </div>
    </div>

    <div className="flex-1 space-y-3 overflow-y-auto p-4">
      {participants.map((participant, index) => {
        const isCurrentUser = currentUserId != null && participant.userId === currentUserId;
        const isAgent = participant.participantType === 'agent';
        const liveSyncEnabled = !isAgent && participant.canLiveSync && !isCurrentUser;
        return (
          <div
            key={participant.userId}
            className={`group rounded-2xl border bg-white p-3.5 shadow-sm transition-all hover:shadow-md ${
              isAgent
                ? 'border-amber-200 bg-gradient-to-br from-amber-50/80 via-white to-orange-50/60 hover:border-amber-300'
                : 'hover:border-blue-200'
            } ${
              isCurrentUser ? 'border-blue-200 ring-1 ring-blue-100' : isAgent ? '' : 'border-slate-200'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="relative shrink-0">
                <div
                  className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold text-white shadow-sm ${
                    isAgent ? 'bg-gradient-to-br from-amber-500 to-orange-500' : palette[index % palette.length]
                  }`}
                >
                  {isAgent ? <Bot size={16} /> : participant.name.charAt(0)}
                </div>
                <span
                  className={`absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-2 border-white ${
                    participant.online ? (isAgent ? 'bg-amber-500' : 'bg-emerald-500') : 'bg-slate-300'
                  }`}
                />
              </div>

              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold tracking-tight text-slate-800">
                  {participant.name}
                  {isCurrentUser ? '（你）' : ''}
                </p>
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  {normalizeRoleLabel(participant)}
                </p>
              </div>
            </div>

            {isAgent ? (
              <div className="mt-3 rounded-xl border border-amber-100 bg-white/85 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600">角色智能体</span>
                  {participant.agentShortcutKey ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-amber-700">
                      <Keyboard size={10} />
                      {participant.agentShortcutKey}
                    </span>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="mt-3 rounded-xl bg-slate-50 p-2.5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">共享</span>
                  {participant.publicShareCount > 0 ? (
                    <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-emerald-600">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      已公开
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-slate-300">
                      <Lock size={10} />
                      私有
                    </span>
                  )}
                </div>

                <button
                  type="button"
                  disabled={!liveSyncEnabled}
                  onClick={() => liveSyncEnabled && onLiveSync?.(participant)}
                  className={`flex h-12 w-full items-center justify-center rounded-xl border text-[11px] font-bold uppercase tracking-wider transition ${
                    liveSyncEnabled
                      ? 'border-blue-50 bg-white text-blue-500 hover:border-blue-200 hover:bg-blue-50'
                      : 'cursor-not-allowed border-dashed border-slate-100 text-slate-300'
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <View size={13} />
                    实时同步
                  </span>
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  </>
);

const ParticipantSidebar: React.FC<ParticipantSidebarProps> = ({
  participants = [],
  currentUserId,
  onLiveSync,
  collapsible = false,
  defaultCollapsed = false,
}) => {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const sortedParticipants = useMemo(
    () =>
      [...participants].sort((a, b) => {
        const getRank = (participant: SessionMemberDirectoryEntry): number => {
          if (participant.role === 'host') return 0;
          if (participant.participantType === 'agent') return 1;
          if (participant.role === 'designer') return 2;
          return 3;
        };
        const rankDiff = getRank(a) - getRank(b);
        if (rankDiff !== 0) {
          return rankDiff;
        }
        if (a.participantType === 'agent' || b.participantType === 'agent') {
          return a.name.localeCompare(b.name);
        }
        if (a.role === b.role) {
          return a.userId - b.userId;
        }
        return a.role.localeCompare(b.role);
      }),
    [participants],
  );

  if (!collapsible) {
    return (
      <aside className="z-20 flex w-[17.5rem] flex-col border-l border-slate-200 bg-slate-50/50">
        <ParticipantSidebarContent
          participants={sortedParticipants}
          currentUserId={currentUserId}
          onLiveSync={onLiveSync}
        />
      </aside>
    );
  }

  return (
    <aside
      className={`relative shrink-0 border-l border-slate-200 bg-slate-50 transition-all duration-300 ${
        collapsed ? 'w-0' : 'w-[18rem]'
      }`}
    >
      <button
        type="button"
        onClick={() => setCollapsed((prev) => !prev)}
        className="absolute -left-3 top-1/2 z-30 flex h-12 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm transition hover:text-slate-700"
      >
        {collapsed ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
      </button>

      <div className={`flex h-full flex-col overflow-hidden transition-opacity duration-300 ${collapsed ? 'opacity-0' : 'opacity-100'}`}>
        <ParticipantSidebarContent
          participants={sortedParticipants}
          currentUserId={currentUserId}
          onLiveSync={onLiveSync}
          onCollapse={() => setCollapsed(true)}
          collapsible
        />
      </div>
    </aside>
  );
};

export default ParticipantSidebar;
