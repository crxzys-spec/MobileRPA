import { mrpaApi } from "../api/mrpa";
import type {
  StreamSessionConfigRequest,
  StreamSessionStatus,
  WebRTCAnswer,
  WebRTCOffer,
  WebrtcConfig,
} from "../api/types";

export const streamsService = {
  getWebRTCConfig(): Promise<WebrtcConfig> {
    return mrpaApi.getWebRTCConfig();
  },
  sendOffer(payload: WebRTCOffer): Promise<WebRTCAnswer> {
    return mrpaApi.webrtcOffer(payload);
  },
  getStreamSession(deviceId: string): Promise<StreamSessionStatus> {
    return mrpaApi.getStreamSession(deviceId);
  },
  startStreamSession(
    deviceId: string,
    payload?: StreamSessionConfigRequest,
  ): Promise<StreamSessionStatus> {
    return mrpaApi.startStreamSession(deviceId, payload);
  },
  restartStreamSession(
    deviceId: string,
    payload?: StreamSessionConfigRequest,
  ): Promise<StreamSessionStatus> {
    return mrpaApi.restartStreamSession(deviceId, payload);
  },
  stopStreamSession(deviceId: string): Promise<StreamSessionStatus> {
    return mrpaApi.stopStreamSession(deviceId);
  },
  updateStreamSessionConfig(
    deviceId: string,
    payload: StreamSessionConfigRequest,
  ): Promise<StreamSessionStatus> {
    return mrpaApi.updateStreamSessionConfig(deviceId, payload);
  },
};
