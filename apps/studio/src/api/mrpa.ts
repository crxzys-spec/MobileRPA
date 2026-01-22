import { fetchJson } from "../client/http";
import type {
  Device,
  DeviceCommand,
  DeviceCommandRequest,
  DeviceQueueClearResponse,
  DeviceSessionCloseResponse,
  DeviceSession,
  RunMeta,
  RunLogResponse,
  RunRequest,
  StreamSessionConfigRequest,
  StreamSessionStatus,
  StepDetails,
  StopRunResponse,
  WebRTCAnswer,
  WebRTCOffer,
  WebrtcConfig,
} from "./types";

export const mrpaApi = {
  listRuns: () => fetchJson<RunMeta[]>("/api/runs"),
  listDevices: () => fetchJson<Device[]>("/api/devices"),
  getRun: (runId: string) =>
    fetchJson<RunMeta>(`/api/runs/${encodeURIComponent(runId)}`),
  getStep: (runId: string, stepId: string) =>
    fetchJson<StepDetails>(
      `/api/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}`,
    ),
  getRunLog: (runId: string, limit = 200) =>
    fetchJson<RunLogResponse>(
      `/api/runs/${encodeURIComponent(runId)}/log?limit=${limit}`,
    ),
  getWebRTCConfig: () => fetchJson<WebrtcConfig>("/api/webrtc/config"),
  startRun: (payload: RunRequest) =>
    fetchJson<RunMeta>("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  webrtcOffer: (payload: WebRTCOffer) =>
    fetchJson<WebRTCAnswer>("/api/webrtc/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getStreamSession: (deviceId: string) =>
    fetchJson<StreamSessionStatus>(
      `/api/stream/${encodeURIComponent(deviceId)}/session`,
    ),
  startStreamSession: (
    deviceId: string,
    payload?: StreamSessionConfigRequest,
  ) =>
    fetchJson<StreamSessionStatus>(
      `/api/stream/${encodeURIComponent(deviceId)}/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload ?? {}),
      },
    ),
  restartStreamSession: (
    deviceId: string,
    payload?: StreamSessionConfigRequest,
  ) =>
    fetchJson<StreamSessionStatus>(
      `/api/stream/${encodeURIComponent(deviceId)}/restart`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload ?? {}),
      },
    ),
  stopStreamSession: (deviceId: string) =>
    fetchJson<StreamSessionStatus>(
      `/api/stream/${encodeURIComponent(deviceId)}/stop`,
      { method: "POST" },
    ),
  updateStreamSessionConfig: (
    deviceId: string,
    payload: StreamSessionConfigRequest,
  ) =>
    fetchJson<StreamSessionStatus>(
      `/api/stream/${encodeURIComponent(deviceId)}/config`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  stopRun: (runId: string) =>
    fetchJson<StopRunResponse>(`/api/runs/${encodeURIComponent(runId)}/stop`, {
      method: "POST",
    }),
  listDeviceSessions: () =>
    fetchJson<DeviceSession[]>("/api/device/sessions"),
  getDeviceSession: (deviceId: string) =>
    fetchJson<DeviceSession>(
      `/api/device/${encodeURIComponent(deviceId)}/session`,
    ),
  listDeviceCommands: (deviceId: string, limit = 50) =>
    fetchJson<DeviceCommand[]>(
      `/api/device/${encodeURIComponent(deviceId)}/commands?limit=${limit}`,
    ),
  enqueueDeviceCommand: (deviceId: string, payload: DeviceCommandRequest) =>
    fetchJson<DeviceCommand>(
      `/api/device/${encodeURIComponent(deviceId)}/commands`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  clearDeviceQueue: (deviceId: string) =>
    fetchJson<DeviceQueueClearResponse>(
      `/api/device/${encodeURIComponent(deviceId)}/queue/clear`,
      { method: "POST" },
    ),
  closeDeviceSession: (deviceId: string) =>
    fetchJson<DeviceSessionCloseResponse>(
      `/api/device/${encodeURIComponent(deviceId)}/session/close`,
      { method: "POST" },
    ),
};
