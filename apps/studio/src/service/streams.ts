import { mrpaApi } from "../api/mrpa";
import type { WebRTCAnswer, WebRTCOffer, WebrtcConfig } from "../api/types";

export const streamsService = {
  getWebRTCConfig(): Promise<WebrtcConfig> {
    return mrpaApi.getWebRTCConfig();
  },
  sendOffer(payload: WebRTCOffer): Promise<WebRTCAnswer> {
    return mrpaApi.webrtcOffer(payload);
  },
};
