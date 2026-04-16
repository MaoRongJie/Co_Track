import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  Hand,
  LogOut,
  Mic,
  MicOff,
  MonitorSpeaker,
  Video,
  VideoOff,
} from 'lucide-react';
import type { MeetingRole, PeerMediaState } from '../types/meeting.ts';

interface MeetingDockProps {
  role: MeetingRole;
  localUserName: string;
  localStream: MediaStream | null;
  audioEnabled: boolean;
  videoEnabled: boolean;
  canPublishMedia: boolean;
  handRaised: boolean;
  peers: PeerMediaState[];
  connecting: boolean;
  joined: boolean;
  error: string | null;
  onToggleAudio: () => void | Promise<void>;
  onToggleVideo: () => void | Promise<void>;
  onLeave: () => void;
  onRequestSpeak: () => void;
  onApproveSpeak: (targetUserId: number) => void;
}

const roleText: Record<MeetingRole, string> = {
  host: '主持人',
  designer: '设计师',
  observer: '观察者',
};

const VideoTile: React.FC<{
  stream: MediaStream | null | undefined;
  label: string;
  muted?: boolean;
  audioEnabled: boolean;
  videoEnabled: boolean;
  role: MeetingRole;
  handRaised?: boolean;
  speakGranted?: boolean;
}> = ({ stream, label, muted, audioEnabled, videoEnabled, role, handRaised, speakGranted }) => {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!videoRef.current) {
      return;
    }
    videoRef.current.srcObject = stream ?? null;
  }, [stream]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-900">
      <div className="aspect-video w-full">
        {videoEnabled && stream ? (
          <video ref={videoRef} autoPlay playsInline muted={muted} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-slate-800 text-slate-300">
            <VideoOff size={18} />
          </div>
        )}
      </div>
      <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-black/60 px-2 py-1 text-[11px] text-white">
        <div className="flex items-center gap-1">
          <span className="font-semibold">{label}</span>
          <span className="rounded bg-white/20 px-1 py-0.5">{roleText[role]}</span>
          {handRaised ? <span className="rounded bg-amber-500/80 px-1 py-0.5">举手中</span> : null}
          {speakGranted ? <span className="rounded bg-emerald-500/80 px-1 py-0.5">已批准</span> : null}
        </div>
        <div className="flex items-center gap-1">
          {audioEnabled ? <Mic size={12} /> : <MicOff size={12} />}
          {videoEnabled ? <Video size={12} /> : <VideoOff size={12} />}
        </div>
      </div>
    </div>
  );
};

const MeetingDock: React.FC<MeetingDockProps> = ({
  role,
  localUserName,
  localStream,
  audioEnabled,
  videoEnabled,
  canPublishMedia,
  handRaised,
  peers,
  connecting,
  joined,
  error,
  onToggleAudio,
  onToggleVideo,
  onLeave,
  onRequestSpeak,
  onApproveSpeak,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const isHost = role === 'host';
  const isObserver = role === 'observer';

  const pendingSpeakRequests = useMemo(
    () => peers.filter((peer) => peer.role === 'observer' && peer.handRaised && !peer.speakGranted),
    [peers],
  );

  return (
    <aside className="fixed bottom-4 right-4 z-50 w-[380px] max-w-[94vw] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2">
        <div className="flex items-center gap-2">
          <MonitorSpeaker size={16} className="text-blue-600" />
          <span className="text-sm font-semibold text-slate-800">会议音视频</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
            {connecting ? '连接中' : joined ? '已连接' : '未连接'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((prev) => !prev)}
          className="rounded-md p-1 text-slate-500 transition hover:bg-slate-200"
        >
          {collapsed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {!collapsed ? (
        <div className="space-y-3 p-3">
          {error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>
          ) : null}

          <div className="grid grid-cols-2 gap-2">
            <VideoTile
              stream={localStream}
              label={`${localUserName}（我）`}
              muted
              audioEnabled={audioEnabled}
              videoEnabled={videoEnabled}
              role={role}
              handRaised={handRaised}
              speakGranted={canPublishMedia}
            />
            {peers.slice(0, 5).map((peer) => (
              <VideoTile
                key={peer.userId}
                stream={peer.stream}
                label={peer.name}
                audioEnabled={peer.audioEnabled}
                videoEnabled={peer.videoEnabled}
                role={peer.role}
                handRaised={peer.handRaised}
                speakGranted={peer.speakGranted}
              />
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                void onToggleAudio();
              }}
              className={`inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold ${
                audioEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-700'
              }`}
            >
              {audioEnabled ? <Mic size={14} /> : <MicOff size={14} />}
              {audioEnabled ? '麦克风开' : '麦克风关'}
            </button>

            <button
              type="button"
              onClick={() => {
                void onToggleVideo();
              }}
              className={`inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold ${
                videoEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-700'
              }`}
            >
              {videoEnabled ? <Video size={14} /> : <VideoOff size={14} />}
              {videoEnabled ? '摄像头开' : '摄像头关'}
            </button>

            {isObserver ? (
              <button
                type="button"
                onClick={onRequestSpeak}
                className="inline-flex items-center gap-1 rounded-lg bg-amber-100 px-3 py-1.5 text-xs font-semibold text-amber-700"
              >
                <Hand size={14} />
                {handRaised ? '已申请发言' : '申请发言'}
              </button>
            ) : null}

            <button
              type="button"
              onClick={onLeave}
              className="ml-auto inline-flex items-center gap-1 rounded-lg bg-rose-100 px-3 py-1.5 text-xs font-semibold text-rose-700"
            >
              <LogOut size={14} />
              离开会议
            </button>
          </div>

          {isHost && pendingSpeakRequests.length > 0 ? (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-2">
              <p className="mb-1 text-xs font-semibold text-blue-700">发言申请</p>
              <div className="space-y-1">
                {pendingSpeakRequests.map((peer) => (
                  <div key={peer.userId} className="flex items-center justify-between rounded bg-white px-2 py-1">
                    <span className="text-xs text-slate-700">{peer.name}</span>
                    <button
                      type="button"
                      onClick={() => onApproveSpeak(peer.userId)}
                      className="rounded bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white"
                    >
                      批准
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
};

export default MeetingDock;
