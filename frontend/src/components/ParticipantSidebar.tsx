import React from 'react';
import { MessageSquare, MoreHorizontal, Users, View, Lock } from 'lucide-react';

interface Participant {
  id: number;
  name: string;
  role: 'host' | 'designer' | 'observer';
  online: boolean;
  shared: boolean;
  color: string;
}

interface ParticipantSidebarProps {
  onReference?: (participantName: string) => void;
}

const participants: Participant[] = [
  { id: 1, name: 'Mia Chen', role: 'host', online: true, shared: true, color: 'bg-blue-500' },
  { id: 2, name: 'Leo Wang', role: 'designer', online: true, shared: true, color: 'bg-emerald-500' },
  { id: 3, name: 'Ava Zhao', role: 'designer', online: true, shared: false, color: 'bg-amber-500' },
  { id: 4, name: 'Noah Zhou', role: 'designer', online: false, shared: false, color: 'bg-slate-400' },
  { id: 5, name: 'Ivy Lin', role: 'observer', online: true, shared: false, color: 'bg-fuchsia-500' },
];

const roleLabelMap: Record<Participant['role'], string> = {
  host: 'Host',
  designer: 'Designer',
  observer: 'Observer',
};

const ParticipantSidebar: React.FC<ParticipantSidebarProps> = ({ onReference }) => (
  <aside className="z-20 flex w-[17.5rem] flex-col border-l border-slate-200 bg-slate-50/50">
    <div className="flex items-center justify-between border-b border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <Users size={16} className="text-slate-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
          Team ({participants.length})
        </span>
      </div>
      <button
        type="button"
        className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
      >
        <MoreHorizontal size={14} />
      </button>
    </div>

    <div className="flex-1 space-y-3 overflow-y-auto p-4">
      {participants.map((participant) => (
        <div
          key={participant.id}
          className="group rounded-2xl border border-slate-200 bg-white p-3.5 shadow-sm transition-all hover:border-blue-200 hover:shadow-md"
        >
          {/* Header: Avatar, Info & Options */}
          <div className="flex items-center gap-3">
            <div className="relative shrink-0">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold text-white shadow-sm ${participant.color}`}
              >
                {participant.name.charAt(0)}
              </div>
              <span
                className={`absolute bottom-0 right-0 h-3.5 w-3.5 rounded-full border-2 border-white ${
                  participant.online ? 'bg-emerald-500' : 'bg-slate-300'
                }`}
              />
            </div>

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-800">{participant.name}</p>
              <p className="text-[11px] font-medium text-slate-500">{roleLabelMap[participant.role]}</p>
            </div>

            {participant.shared ? (
              <button
                type="button"
                onClick={() => onReference?.(participant.name)}
                className="shrink-0 rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-600 transition-colors hover:bg-blue-600 hover:text-white"
              >
                Reference
              </button>
            ) : null}
          </div>

          {/* Canvas Status Area */}
          <div className="mt-3 rounded-xl bg-slate-50 p-2.5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Workspace</span>
              {participant.shared ? (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Shared
                </span>
              ) : (
                <span className="flex items-center gap-1 text-[10px] font-medium text-slate-400">
                  <Lock size={10} />
                  Private
                </span>
              )}
            </div>

            {participant.shared ? (
              <div className="flex h-12 w-full items-center justify-center rounded-lg border border-blue-100 bg-gradient-to-r from-blue-50 to-indigo-50/50">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-blue-500">
                  <View size={13} />
                  Viewing active canvas
                </div>
              </div>
            ) : (
              <div className="flex h-12 w-full items-center justify-center rounded-lg border border-dashed border-slate-200">
                <span className="text-[11px] text-slate-400">No shared access</span>
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="mt-2 flex opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <button
              type="button"
              className="flex w-full items-center justify-center gap-1.5 rounded-lg py-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-blue-600"
            >
              <MessageSquare size={13} />
              Message
            </button>
          </div>
        </div>
      ))}
    </div>
  </aside>
);

export default ParticipantSidebar;

