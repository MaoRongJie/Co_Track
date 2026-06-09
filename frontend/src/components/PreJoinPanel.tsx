import React, { useEffect, useRef, useState } from 'react';
import { Camera, CheckCircle2, Mic, RefreshCw, ShieldAlert } from 'lucide-react';
import type { MeetingRole, PreJoinSettings } from '../types/meeting.ts';

interface PreJoinPanelProps {
  role: MeetingRole;
  onRoleChange: (role: MeetingRole) => void;
  onBack: () => void;
  onJoin: (settings: PreJoinSettings) => Promise<void>;
  joining: boolean;
}

const roleText: Record<MeetingRole, string> = {
  host: '主持人',
  designer: '设计师',
  observer: '观察员',
};

const PreJoinPanel: React.FC<PreJoinPanelProps> = ({ role, onRoleChange, onBack, onJoin, joining }) => {
  const [audioEnabled, setAudioEnabled] = useState(role === 'observer' ? false : false);
  const [videoEnabled, setVideoEnabled] = useState(role === 'observer' ? false : true);
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState<string>('');
  const [selectedVideoDeviceId, setSelectedVideoDeviceId] = useState<string>('');
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [checkDone, setCheckDone] = useState(false);
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);
  const [checking, setChecking] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (role === 'observer') {
      setAudioEnabled(false);
      setVideoEnabled(false);
    } else {
      setAudioEnabled(false);
      setVideoEnabled(true);
    }
    setCheckDone(false);
    setPermissionError(null);
  }, [role]);

  useEffect(() => {
    if (!videoRef.current) {
      return;
    }
    videoRef.current.srcObject = localStream ?? null;
  }, [localStream]);

  useEffect(() => {
    return () => {
      if (localStream) {
        localStream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [localStream]);

  useEffect(() => {
    const initDevices = async () => {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audios = devices.filter((device) => device.kind === 'audioinput');
        const videos = devices.filter((device) => device.kind === 'videoinput');
        setAudioDevices(audios);
        setVideoDevices(videos);
        if (!selectedAudioDeviceId && audios[0]) {
          setSelectedAudioDeviceId(audios[0].deviceId);
        }
        if (!selectedVideoDeviceId && videos[0]) {
          setSelectedVideoDeviceId(videos[0].deviceId);
        }
      } catch {
        // ignore device list errors before permission is granted
      }
    };
    void initDevices();
  }, [selectedAudioDeviceId, selectedVideoDeviceId]);

  useEffect(() => {
    if (!localStream) {
      setAudioLevel(0);
      return;
    }

    const audioTracks = localStream.getAudioTracks();
    if (audioTracks.length === 0 || !audioEnabled) {
      setAudioLevel(0);
      return;
    }

    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(localStream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    source.connect(analyser);

    let rafId = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i += 1) {
        const normalized = (dataArray[i] - 128) / 128;
        sum += normalized * normalized;
      }
      const rms = Math.sqrt(sum / dataArray.length);
      setAudioLevel(Math.min(100, Math.round(rms * 180)));
      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafId);
      source.disconnect();
      analyser.disconnect();
      void audioContext.close();
    };
  }, [audioEnabled, localStream]);

  const updateDevices = async () => {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const audios = devices.filter((device) => device.kind === 'audioinput');
    const videos = devices.filter((device) => device.kind === 'videoinput');
    setAudioDevices(audios);
    setVideoDevices(videos);
    if (!selectedAudioDeviceId && audios[0]) {
      setSelectedAudioDeviceId(audios[0].deviceId);
    }
    if (!selectedVideoDeviceId && videos[0]) {
      setSelectedVideoDeviceId(videos[0].deviceId);
    }
  };

  const runDeviceCheck = async () => {
    setChecking(true);
    setPermissionError(null);
    setCheckDone(false);

    try {
      if (role === 'observer') {
        await updateDevices();
        if (localStream) {
          localStream.getTracks().forEach((track) => track.stop());
        }
        setLocalStream(null);
        setCheckDone(true);
        return;
      }

      // Preload media permissions before entering the room.
      const constraints: MediaStreamConstraints = {
        audio: selectedAudioDeviceId ? { deviceId: { exact: selectedAudioDeviceId } } : true,
        video: selectedVideoDeviceId ? { deviceId: { exact: selectedVideoDeviceId } } : true,
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      stream.getAudioTracks().forEach((track) => {
        track.enabled = audioEnabled;
      });
      stream.getVideoTracks().forEach((track) => {
        track.enabled = videoEnabled;
      });

      if (localStream) {
        localStream.getTracks().forEach((track) => track.stop());
      }
      setLocalStream(stream);
      await updateDevices();
      setCheckDone(true);
    } catch (error) {
      console.error(error);
      setPermissionError('设备不可用。');
    } finally {
      setChecking(false);
    }
  };

  const handleJoin = async () => {
    if (!checkDone || joining) {
      return;
    }

    await onJoin({
      role,
      audioEnabled,
      videoEnabled,
      selectedAudioDeviceId,
      selectedVideoDeviceId,
      localStream,
    });
  };

  const isObserver = role === 'observer';

  return (
    <div className="w-full max-w-3xl rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-800">设备检查</h3>
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          返回
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-900">
            <div className="aspect-video w-full">
              {videoEnabled && localStream ? (
                <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-slate-300">
                  <Camera size={20} />
                </div>
              )}
            </div>
          </div>

          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex items-center justify-between text-xs text-slate-600">
              <span className="inline-flex items-center gap-1">
                <Mic size={12} />
                麦克风
              </span>
              <span>{audioLevel}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-200">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${audioLevel}%` }} />
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <label className="block text-sm text-slate-700">
            角色
            <select
              value={role}
              onChange={(event) => onRoleChange(event.target.value as MeetingRole)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            >
              {(['host', 'designer', 'observer'] as MeetingRole[]).map((item) => (
                <option key={item} value={item}>
                  {roleText[item]}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm text-slate-700">
            麦克风设备
            <select
              value={selectedAudioDeviceId}
              onChange={(event) => {
                setSelectedAudioDeviceId(event.target.value);
                setCheckDone(false);
              }}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            >
              {audioDevices.length === 0 ? <option value="">默认设备</option> : null}
              {audioDevices.map((device) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `麦克风 ${device.deviceId.slice(0, 6)}`}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm text-slate-700">
            摄像头
            <select
              value={selectedVideoDeviceId}
              onChange={(event) => {
                setSelectedVideoDeviceId(event.target.value);
                setCheckDone(false);
              }}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
            >
              {videoDevices.length === 0 ? <option value="">默认设备</option> : null}
              {videoDevices.map((device) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `摄像头 ${device.deviceId.slice(0, 6)}`}
                </option>
              ))}
            </select>
          </label>

          <div className="flex gap-2">
            <button
              type="button"
              disabled={isObserver}
              onClick={() => {
                setAudioEnabled((prev) => !prev);
                setCheckDone(false);
              }}
              className={`rounded-lg px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                audioEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'
              }`}
            >
              {audioEnabled ? '麦克风开' : '麦克风关'}
            </button>
            <button
              type="button"
              disabled={isObserver}
              onClick={() => {
                setVideoEnabled((prev) => !prev);
                setCheckDone(false);
              }}
              className={`rounded-lg px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                videoEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'
              }`}
            >
              {videoEnabled ? '摄像头开' : '摄像头关'}
            </button>
          </div>

          {permissionError ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              <div className="mb-1 inline-flex items-center gap-1">
                <ShieldAlert size={12} />
                检查失败
              </div>
              <p>{permissionError}</p>
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                void runDeviceCheck();
              }}
              disabled={checking}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50"
            >
              <RefreshCw size={12} />
              {checking ? '检查中...' : '检查'}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleJoin();
              }}
              disabled={!checkDone || joining}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              <CheckCircle2 size={12} />
              {joining ? '进入中...' : '进入'}
            </button>
          </div>

        </div>
      </div>
    </div>
  );
};

export default PreJoinPanel;
