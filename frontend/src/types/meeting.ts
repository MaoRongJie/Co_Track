import type { DesignBrief, ProductCategory, ProductProfile } from './design.ts';

export type MeetingRole = 'host' | 'designer' | 'observer';
export type MeetingSettingsSectionId =
  | 'review_roles'
  | 'passenger_evaluation'
  | 'engineering_evaluation'
  | 'collaboration_rules'
  | 'meeting_workflow'
  | 'export_preferences';

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
  session_settings?: MeetingSettings | null;
  settings_permissions?: MeetingSettingsPermissions | null;
  settings_sections?: MeetingSettingsSection[];
  created_at: string;
}

export interface JoinSessionResponse {
  session: JoinedSession;
  role: MeetingRole;
}

export interface SessionMemberDirectoryEntry {
  userId: number;
  name: string;
  role: MeetingRole;
  joinedAt: string;
  online: boolean;
  publicShareCount: number;
  canLiveSync: boolean;
  sharedResultIds: string[];
  participantType?: 'human' | 'agent';
  roleLabel?: string;
  agentShortcutKey?: string;
  agentDescription?: string;
}

export interface SessionMembersResponse {
  sessionId: number;
  members: SessionMemberDirectoryEntry[];
}

export interface PassengerEvaluationConfig {
  displayName: string;
  identitySummary: string;
  preferenceTags: string[];
  dislikeTags: string[];
  focusPoints: string[];
}

export interface EngineeringEvaluationConfig {
  displayName: string;
  identitySummary: string;
  priorityTags: string[];
  riskFocus: string[];
  focusPoints: string[];
}

export interface ReviewPersonaRoleConfig {
  id: string;
  type: 'passenger' | 'engineering' | 'custom';
  enabled: boolean;
  displayName: string;
  identitySummary: string;
  rolePrompt?: string | null;
  focusPoints: string[];
  preferenceTags: string[];
  dislikeTags: string[];
  priorityTags: string[];
  riskFocus: string[];
}

export interface MeetingSettings {
  revision: number;
  updatedAt: string | null;
  updatedByUserId: number | null;
  reviewPersonas: {
    passenger: PassengerEvaluationConfig;
    engineering: EngineeringEvaluationConfig;
    roles: ReviewPersonaRoleConfig[];
  };
}

export interface MeetingSettingsPermissions {
  role: MeetingRole;
  canEdit: boolean;
}

export interface MeetingSettingsSection {
  id: MeetingSettingsSectionId;
  label: string;
  description: string;
  enabled: boolean;
  badge: string | null;
}

export interface MeetingSettingsState {
  sessionId: number;
  sessionSettings: MeetingSettings;
  settingsPermissions: MeetingSettingsPermissions;
  sections: MeetingSettingsSection[];
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
