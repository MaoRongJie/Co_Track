/* eslint-disable react-hooks/set-state-in-effect */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { io, type Socket } from 'socket.io-client';
import type { AuthUser, MeetingRole, PeerMediaState } from '../types/meeting.ts';
import { fetchRtcConfig, getApiBaseUrl } from '../services/apiClient.ts';

type ServerPeer = {
  user_id: number;
  name: string;
  role: MeetingRole;
  audio_enabled: boolean;
  video_enabled: boolean;
  hand_raised: boolean;
  speak_granted: boolean;
};

type JoinAck = {
  ok: boolean;
  error?: string;
  peers?: ServerPeer[];
  limit?: number;
  room_size?: number;
  ice_servers?: RTCIceServer[];
};

type StageChangedPayload = {
  session_id: number;
  stage: string;
};

type BriefPublishedPayload = {
  session_id: number;
  brief_json: unknown;
};

type ModelTaskStatusPayload = {
  session_id: number;
  task_id: number;
  status: string;
  progress: number;
  pipeline_stage?: string | null;
  progress_message?: string | null;
};

type ModelReadyPayload = {
  session_id: number;
  task_id?: number;
  model?: unknown;
};

type ModelLockedPayload = {
  session_id: number;
  base_model_id?: number;
  model_locked_at?: string | null;
  model?: unknown;
};

type TexturePlanUpdatedPayload = {
  session_id: number;
  texture_plan?: unknown;
};

type TextureModelsUpdatedPayload = {
  session_id: number;
  texture_models?: unknown;
};

interface UseMeetingRtcOptions {
  enabled: boolean;
  token: string | null;
  sessionId: number | null;
  user: AuthUser | null;
  role: MeetingRole;
  initialStream: MediaStream | null;
  initialAudioEnabled: boolean;
  initialVideoEnabled: boolean;
  selectedAudioDeviceId?: string;
  selectedVideoDeviceId?: string;
  onStageChanged?: (payload: StageChangedPayload) => void;
  onBriefPublished?: (payload: BriefPublishedPayload) => void;
  onModelTaskStatus?: (payload: ModelTaskStatusPayload) => void;
  onModelReady?: (payload: ModelReadyPayload) => void;
  onModelLocked?: (payload: ModelLockedPayload) => void;
  onTexturePlanUpdated?: (payload: TexturePlanUpdatedPayload) => void;
  onTextureModelsUpdated?: (payload: TextureModelsUpdatedPayload) => void;
}

interface UseMeetingRtcResult {
  joined: boolean;
  connecting: boolean;
  error: string | null;
  roomLimitReached: boolean;
  localStream: MediaStream | null;
  audioEnabled: boolean;
  videoEnabled: boolean;
  canPublishMedia: boolean;
  handRaised: boolean;
  peers: PeerMediaState[];
  toggleAudio: () => Promise<void>;
  toggleVideo: () => Promise<void>;
  requestSpeak: () => void;
  approveSpeak: (targetUserId: number) => void;
  leaveMeeting: () => void;
}

const SOCKET_URL = import.meta.env.VITE_SOCKET_URL ?? getApiBaseUrl();
const FALLBACK_ICE_SERVERS: RTCIceServer[] = [
  { urls: import.meta.env.VITE_STUN_URL ?? 'stun:stun.l.google.com:19302' },
];

const peerFromServer = (peer: ServerPeer): PeerMediaState => ({
  userId: peer.user_id,
  name: peer.name,
  role: peer.role,
  audioEnabled: peer.audio_enabled,
  videoEnabled: peer.video_enabled,
  handRaised: peer.hand_raised,
  speakGranted: peer.speak_granted,
});

export const useMeetingRtc = (options: UseMeetingRtcOptions): UseMeetingRtcResult => {
  const {
    enabled,
    token,
    sessionId,
    user,
    role,
    initialStream,
    initialAudioEnabled,
    initialVideoEnabled,
    selectedAudioDeviceId,
    selectedVideoDeviceId,
    onStageChanged,
    onBriefPublished,
    onModelTaskStatus,
    onModelReady,
    onModelLocked,
    onTexturePlanUpdated,
    onTextureModelsUpdated,
  } = options;

  const socketRef = useRef<Socket | null>(null);
  const pcsRef = useRef<Map<number, RTCPeerConnection>>(new Map());
  const remoteStreamsRef = useRef<Map<number, MediaStream>>(new Map());
  const candidateQueueRef = useRef<Map<number, RTCIceCandidateInit[]>>(new Map());
  const iceServersRef = useRef<RTCIceServer[]>(FALLBACK_ICE_SERVERS);
  const sessionIdRef = useRef<number>(sessionId ?? 0);

  const [joined, setJoined] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roomLimitReached, setRoomLimitReached] = useState(false);
  const [localStream, setLocalStream] = useState<MediaStream | null>(initialStream);
  const [audioEnabled, setAudioEnabled] = useState<boolean>(initialAudioEnabled);
  const [videoEnabled, setVideoEnabled] = useState<boolean>(initialVideoEnabled);
  const [canPublishMedia, setCanPublishMedia] = useState<boolean>(role !== 'observer');
  const [handRaised, setHandRaised] = useState(false);
  const [peers, setPeers] = useState<Record<number, PeerMediaState>>({});

  const localStreamRef = useRef<MediaStream | null>(initialStream);
  const audioEnabledRef = useRef<boolean>(initialAudioEnabled);
  const videoEnabledRef = useRef<boolean>(initialVideoEnabled);
  const canPublishMediaRef = useRef<boolean>(role !== 'observer');
  const onStageChangedRef = useRef(onStageChanged);
  const onBriefPublishedRef = useRef(onBriefPublished);
  const onModelTaskStatusRef = useRef(onModelTaskStatus);
  const onModelReadyRef = useRef(onModelReady);
  const onModelLockedRef = useRef(onModelLocked);
  const onTexturePlanUpdatedRef = useRef(onTexturePlanUpdated);
  const onTextureModelsUpdatedRef = useRef(onTextureModelsUpdated);

  useEffect(() => {
    sessionIdRef.current = sessionId ?? 0;
  }, [sessionId]);

  useEffect(() => {
    localStreamRef.current = localStream;
  }, [localStream]);

  useEffect(() => {
    audioEnabledRef.current = audioEnabled;
  }, [audioEnabled]);

  useEffect(() => {
    videoEnabledRef.current = videoEnabled;
  }, [videoEnabled]);

  useEffect(() => {
    canPublishMediaRef.current = canPublishMedia;
  }, [canPublishMedia]);

  useEffect(() => {
    onStageChangedRef.current = onStageChanged;
  }, [onStageChanged]);

  useEffect(() => {
    onBriefPublishedRef.current = onBriefPublished;
  }, [onBriefPublished]);

  useEffect(() => {
    onModelTaskStatusRef.current = onModelTaskStatus;
  }, [onModelTaskStatus]);

  useEffect(() => {
    onModelReadyRef.current = onModelReady;
  }, [onModelReady]);

  useEffect(() => {
    onModelLockedRef.current = onModelLocked;
  }, [onModelLocked]);

  useEffect(() => {
    onTexturePlanUpdatedRef.current = onTexturePlanUpdated;
  }, [onTexturePlanUpdated]);

  useEffect(() => {
    onTextureModelsUpdatedRef.current = onTextureModelsUpdated;
  }, [onTextureModelsUpdated]);

  useEffect(() => {
    const publishAllowed = role !== 'observer';
    setCanPublishMedia(publishAllowed);
    canPublishMediaRef.current = publishAllowed;
    if (!publishAllowed) {
      setAudioEnabled(false);
      setVideoEnabled(false);
      audioEnabledRef.current = false;
      videoEnabledRef.current = false;
    }
  }, [role]);

  useEffect(() => {
    if (initialStream) {
      setLocalStream(initialStream);
      localStreamRef.current = initialStream;
    }
    setAudioEnabled(initialAudioEnabled);
    setVideoEnabled(initialVideoEnabled);
    audioEnabledRef.current = initialAudioEnabled;
    videoEnabledRef.current = initialVideoEnabled;
  }, [initialAudioEnabled, initialStream, initialVideoEnabled]);

  const cleanupPeer = useCallback((remoteUserId: number) => {
    const pc = pcsRef.current.get(remoteUserId);
    if (pc) {
      pc.onicecandidate = null;
      pc.ontrack = null;
      pc.onconnectionstatechange = null;
      pc.onnegotiationneeded = null;
      pc.close();
      pcsRef.current.delete(remoteUserId);
    }
    remoteStreamsRef.current.delete(remoteUserId);
    candidateQueueRef.current.delete(remoteUserId);
    setPeers((previous) => {
      const next = { ...previous };
      delete next[remoteUserId];
      return next;
    });
  }, []);

  const clearAllPeers = useCallback(() => {
    Array.from(pcsRef.current.keys()).forEach(cleanupPeer);
    setPeers({});
  }, [cleanupPeer]);

  const emitMediaToggle = useCallback((nextAudio: boolean, nextVideo: boolean) => {
    if (!socketRef.current || !sessionIdRef.current) {
      return;
    }
    socketRef.current.emit('media:toggle', {
      session_id: sessionIdRef.current,
      audio_enabled: nextAudio,
      video_enabled: nextVideo,
    });
  }, []);

  const maybeAttachLocalTracks = useCallback((pc: RTCPeerConnection) => {
    const stream = localStreamRef.current;
    if (!stream) {
      return;
    }

    const senders = pc.getSenders();
    stream.getTracks().forEach((track) => {
      const sender = senders.find((item) => item.track?.kind === track.kind);
      if (!sender) {
        pc.addTrack(track, stream);
      } else if (sender.track?.id !== track.id) {
        void sender.replaceTrack(track);
      }
    });
  }, []);

  const flushQueuedCandidates = useCallback(async (remoteUserId: number, pc: RTCPeerConnection) => {
    const queued = candidateQueueRef.current.get(remoteUserId) ?? [];
    if (queued.length === 0) {
      return;
    }
    for (const candidate of queued) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      } catch {
        // ignore single bad candidate
      }
    }
    candidateQueueRef.current.delete(remoteUserId);
  }, []);

  const sendOffer = useCallback(async (remoteUserId: number, providedPc?: RTCPeerConnection) => {
    if (!socketRef.current || !sessionIdRef.current) {
      return;
    }

    const pc = providedPc ?? pcsRef.current.get(remoteUserId);
    if (!pc) {
      return;
    }

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    socketRef.current.emit('webrtc:offer', {
      session_id: sessionIdRef.current,
      to_user_id: remoteUserId,
      sdp: offer,
    });
  }, []);

  const createPeerConnection = useCallback(
    (remoteUserId: number): RTCPeerConnection => {
      const existing = pcsRef.current.get(remoteUserId);
      if (existing) {
        maybeAttachLocalTracks(existing);
        return existing;
      }

      const pc = new RTCPeerConnection({ iceServers: iceServersRef.current });
      maybeAttachLocalTracks(pc);

      pc.onicecandidate = (event) => {
        if (!event.candidate || !socketRef.current || !sessionIdRef.current) {
          return;
        }
        socketRef.current.emit('webrtc:ice_candidate', {
          session_id: sessionIdRef.current,
          to_user_id: remoteUserId,
          candidate: event.candidate.toJSON(),
        });
      };

      pc.ontrack = (event) => {
        const stream = event.streams[0];
        remoteStreamsRef.current.set(remoteUserId, stream);
        setPeers((previous) => {
          const target = previous[remoteUserId];
          if (!target) {
            return previous;
          }
          return {
            ...previous,
            [remoteUserId]: {
              ...target,
              stream,
            },
          };
        });
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
          cleanupPeer(remoteUserId);
        }
      };

      pc.onnegotiationneeded = () => {
        void sendOffer(remoteUserId, pc);
      };

      pcsRef.current.set(remoteUserId, pc);
      void flushQueuedCandidates(remoteUserId, pc);
      return pc;
    },
    [cleanupPeer, flushQueuedCandidates, maybeAttachLocalTracks, sendOffer],
  );

  const createAndSendOffer = useCallback(
    async (remoteUserId: number) => {
      const pc = createPeerConnection(remoteUserId);
      await sendOffer(remoteUserId, pc);
    },
    [createPeerConnection, sendOffer],
  );

  const ensureLocalStream = useCallback(async (): Promise<MediaStream | null> => {
    if (localStreamRef.current) {
      return localStreamRef.current;
    }

    if (!canPublishMediaRef.current) {
      setError('当前角色尚未获得发言权限，无法开启音视频。');
      return null;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedAudioDeviceId ? { deviceId: { exact: selectedAudioDeviceId } } : true,
        video: selectedVideoDeviceId ? { deviceId: { exact: selectedVideoDeviceId } } : true,
      });
      stream.getAudioTracks().forEach((track) => {
        track.enabled = audioEnabledRef.current;
      });
      stream.getVideoTracks().forEach((track) => {
        track.enabled = videoEnabledRef.current;
      });
      localStreamRef.current = stream;
      setLocalStream(stream);
      return stream;
    } catch {
      setError('获取摄像头或麦克风失败，请检查浏览器权限设置。');
      return null;
    }
  }, [selectedAudioDeviceId, selectedVideoDeviceId]);

  const toggleAudio = useCallback(async () => {
    if (!canPublishMediaRef.current) {
      setError('Observer 需要先申请发言并被批准后，才能开启麦克风。');
      return;
    }

    const stream = await ensureLocalStream();
    if (!stream) {
      return;
    }

    const next = !audioEnabledRef.current;
    stream.getAudioTracks().forEach((track) => {
      track.enabled = next;
    });
    audioEnabledRef.current = next;
    setAudioEnabled(next);
    emitMediaToggle(next, videoEnabledRef.current);
    setError(null);
  }, [emitMediaToggle, ensureLocalStream]);

  const toggleVideo = useCallback(async () => {
    if (!canPublishMediaRef.current) {
      setError('Observer 需要先申请发言并被批准后，才能开启摄像头。');
      return;
    }

    const stream = await ensureLocalStream();
    if (!stream) {
      return;
    }

    const next = !videoEnabledRef.current;
    stream.getVideoTracks().forEach((track) => {
      track.enabled = next;
    });
    videoEnabledRef.current = next;
    setVideoEnabled(next);
    emitMediaToggle(audioEnabledRef.current, next);
    setError(null);
  }, [emitMediaToggle, ensureLocalStream]);

  const requestSpeak = useCallback(() => {
    if (!socketRef.current || !sessionIdRef.current || role !== 'observer') {
      return;
    }
    setHandRaised(true);
    socketRef.current.emit('media:speak_request', { session_id: sessionIdRef.current });
  }, [role]);

  const approveSpeak = useCallback(
    (targetUserId: number) => {
      if (!socketRef.current || !sessionIdRef.current || role !== 'host') {
        return;
      }
      socketRef.current.emit('media:speak_approve', {
        session_id: sessionIdRef.current,
        target_user_id: targetUserId,
      });
    },
    [role],
  );

  const leaveMeeting = useCallback(() => {
    const socket = socketRef.current;
    if (socket && sessionIdRef.current) {
      socket.emit('meeting:media_leave', { session_id: sessionIdRef.current });
      socket.disconnect();
    }

    socketRef.current = null;
    clearAllPeers();
    setJoined(false);
    setConnecting(false);
    setRoomLimitReached(false);
    setHandRaised(false);
    setError(null);

    const stream = localStreamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
    localStreamRef.current = null;
    setLocalStream(null);

    const publishAllowed = role !== 'observer';
    setCanPublishMedia(publishAllowed);
    canPublishMediaRef.current = publishAllowed;
  }, [clearAllPeers, role]);

  useEffect(() => {
    if (!localStream) {
      return;
    }

    pcsRef.current.forEach((pc, remoteUserId) => {
      maybeAttachLocalTracks(pc);
      void sendOffer(remoteUserId, pc);
    });
  }, [localStream, maybeAttachLocalTracks, sendOffer]);

  useEffect(() => {
    if (!enabled || !token || !sessionId || !user) {
      return;
    }

    let mounted = true;
    const socket = io(SOCKET_URL, {
      transports: ['websocket'],
      auth: { token },
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    socketRef.current = socket;
    setConnecting(true);
    setError(null);

    const syncIceServers = async () => {
      try {
        const config = await fetchRtcConfig(token);
        if (config.ice_servers.length > 0) {
          iceServersRef.current = config.ice_servers;
        }
      } catch {
        iceServersRef.current = FALLBACK_ICE_SERVERS;
      }
    };

    const doJoin = async () => {
      await syncIceServers();
      socket.emit(
        'meeting:media_join',
        {
          session_id: sessionId,
          audio_enabled: audioEnabledRef.current,
          video_enabled: videoEnabledRef.current,
        },
        async (ack: JoinAck) => {
          if (!mounted) {
            return;
          }

          if (!ack?.ok) {
            setConnecting(false);
            if (ack?.error === 'ROOM_FULL') {
              setRoomLimitReached(true);
              setError('会议人数已达上限（6 人）。');
            } else {
              setError(`加入会议失败：${ack?.error ?? 'UNKNOWN'}`);
            }
            return;
          }

          setJoined(true);
          setConnecting(false);
          setRoomLimitReached(false);
          setError(null);

          const nextPeers: Record<number, PeerMediaState> = {};
          (ack.peers ?? []).forEach((item) => {
            const converted = peerFromServer(item);
            converted.stream = remoteStreamsRef.current.get(converted.userId);
            nextPeers[converted.userId] = converted;
          });
          setPeers(nextPeers);

          for (const peer of ack.peers ?? []) {
            try {
              await createAndSendOffer(peer.user_id);
            } catch {
              // keep room join alive even when one peer fails to negotiate
            }
          }
        },
      );
    };

    socket.on('connect', () => {
      void doJoin();
    });

    socket.on('disconnect', () => {
      if (!mounted) {
        return;
      }
      setJoined(false);
      setConnecting(false);
      clearAllPeers();
    });

    socket.on('meeting:peer_joined', (payload: { session_id: number; peer: ServerPeer }) => {
      if (payload.session_id !== sessionId || payload.peer.user_id === user.id) {
        return;
      }

      setPeers((previous) => ({
        ...previous,
        [payload.peer.user_id]: {
          ...peerFromServer(payload.peer),
          stream: remoteStreamsRef.current.get(payload.peer.user_id),
        },
      }));
    });

    socket.on('meeting:peer_left', (payload: { session_id: number; user_id: number }) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      cleanupPeer(payload.user_id);
    });

    socket.on('media:peer_state', (payload: { session_id: number; peer: ServerPeer }) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      const converted = peerFromServer(payload.peer);
      converted.stream = remoteStreamsRef.current.get(converted.userId);
      setPeers((previous) => ({
        ...previous,
        [converted.userId]: converted,
      }));
    });

    socket.on('media:speak_granted', (payload: { session_id: number; target_user_id: number }) => {
      if (payload.session_id !== sessionId || payload.target_user_id !== user.id) {
        return;
      }
      setCanPublishMedia(true);
      canPublishMediaRef.current = true;
      setHandRaised(false);
    });

    socket.on(
      'webrtc:offer',
      async (payload: { session_id: number; from_user_id: number; sdp: RTCSessionDescriptionInit }) => {
        if (payload.session_id !== sessionId) {
          return;
        }

        try {
          const pc = createPeerConnection(payload.from_user_id);
          await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          socket.emit('webrtc:answer', {
            session_id: sessionId,
            to_user_id: payload.from_user_id,
            sdp: answer,
          });
          await flushQueuedCandidates(payload.from_user_id, pc);
        } catch {
          setError('处理远端 offer 失败。');
        }
      },
    );

    socket.on(
      'webrtc:answer',
      async (payload: { session_id: number; from_user_id: number; sdp: RTCSessionDescriptionInit }) => {
        if (payload.session_id !== sessionId) {
          return;
        }
        const pc = createPeerConnection(payload.from_user_id);
        try {
          await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
        } catch {
          setError('处理远端 answer 失败。');
        }
      },
    );

    socket.on(
      'webrtc:ice_candidate',
      async (payload: { session_id: number; from_user_id: number; candidate: RTCIceCandidateInit }) => {
        if (payload.session_id !== sessionId) {
          return;
        }

        const pc = pcsRef.current.get(payload.from_user_id);
        if (!pc || !pc.remoteDescription) {
          const queued = candidateQueueRef.current.get(payload.from_user_id) ?? [];
          queued.push(payload.candidate);
          candidateQueueRef.current.set(payload.from_user_id, queued);
          return;
        }

        try {
          await pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
        } catch {
          // ignore bad candidate
        }
      },
    );

    socket.on('stage:changed', (payload: StageChangedPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onStageChangedRef.current?.(payload);
    });

    socket.on('brief:published', (payload: BriefPublishedPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onBriefPublishedRef.current?.(payload);
    });

    socket.on('model:task_status', (payload: ModelTaskStatusPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onModelTaskStatusRef.current?.(payload);
    });

    socket.on('model:ready', (payload: ModelReadyPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onModelReadyRef.current?.(payload);
    });

    socket.on('model:locked', (payload: ModelLockedPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onModelLockedRef.current?.(payload);
    });

    socket.on('texture_plan:updated', (payload: TexturePlanUpdatedPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onTexturePlanUpdatedRef.current?.(payload);
    });

    socket.on('texture_models:updated', (payload: TextureModelsUpdatedPayload) => {
      if (payload.session_id !== sessionId) {
        return;
      }
      onTextureModelsUpdatedRef.current?.(payload);
    });

    socket.on('connect_error', () => {
      if (!mounted) {
        return;
      }
      setConnecting(false);
      setError('信令连接失败，请检查后端服务是否已启动。');
    });

    return () => {
      mounted = false;
      socket.removeAllListeners();
      socket.disconnect();
      socketRef.current = null;
      clearAllPeers();
    };
  }, [
    enabled,
    token,
    sessionId,
    user,
    clearAllPeers,
    cleanupPeer,
    createAndSendOffer,
    createPeerConnection,
    flushQueuedCandidates,
  ]);

  useEffect(() => {
    if (!localStream) {
      return;
    }
    localStream.getAudioTracks().forEach((track) => {
      track.enabled = audioEnabled;
    });
    localStream.getVideoTracks().forEach((track) => {
      track.enabled = videoEnabled;
    });
  }, [audioEnabled, localStream, videoEnabled]);

  const peerList = useMemo(
    () =>
      Object.values(peers).sort((a, b) => {
        if (a.role === b.role) {
          return a.userId - b.userId;
        }
        if (a.role === 'host') return -1;
        if (b.role === 'host') return 1;
        return a.role.localeCompare(b.role);
      }),
    [peers],
  );

  return {
    joined,
    connecting,
    error,
    roomLimitReached,
    localStream,
    audioEnabled,
    videoEnabled,
    canPublishMedia,
    handRaised,
    peers: peerList,
    toggleAudio,
    toggleVideo,
    requestSpeak,
    approveSpeak,
    leaveMeeting,
  };
};


