import type { DesignBrief, ProductCategory, ProductProfile } from './design.ts';

export type MeetingRole = 'host' | 'designer' | 'observer';

export type SessionStage =
  | 'LOBBY'
  | 'BRIEFING'
  | 'MODEL_PREPARING'
  | 'DESIGNING'
  | 'COLLECTING'
  | 'REVIEWING'
  | 'PREVIEWING';

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface JoinedSession {
  id: number;
  name: string;
  invite_code: string;
  stage: SessionStage;
  design_goal_text?: string | null;
  product_category?: ProductCategory | null;
  product_profile?: ProductProfile | null;
  brief_json?: DesignBrief | null;
  base_model_id?: number | null;
  model_locked_at?: string | null;
  created_at: string;
}

export interface JoinSessionResponse {
  session: JoinedSession;
  role: MeetingRole;
}

export interface IceConfigResponse {
  ice_servers: RTCIceServer[];
}

export interface PreJoinSettings {
  role: MeetingRole;
  audioEnabled: boolean;
  videoEnabled: boolean;
  selectedAudioDeviceId?: string;
  selectedVideoDeviceId?: string;
  localStream: MediaStream | null;
}

export interface PeerMediaState {
  userId: number;
  name: string;
  role: MeetingRole;
  audioEnabled: boolean;
  videoEnabled: boolean;
  handRaised: boolean;
  speakGranted: boolean;
  stream?: MediaStream;
}

export interface LocalMediaState {
  audioEnabled: boolean;
  videoEnabled: boolean;
  canPublishMedia: boolean;
}
