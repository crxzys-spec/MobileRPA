import type { WebrtcConfig } from "../api/types";

interface RtpCodecCapabilityExtended extends RTCRtpCodecCapability {
  payloadType?: number;
  parameters?: { apt?: number };
}

export function buildIceServers(
  config?: WebrtcConfig | null,
): RTCIceServer[] {
  const entries = Array.isArray(config?.ice_servers) ? config.ice_servers : [];
  const servers: RTCIceServer[] = [];
  entries.forEach((entry) => {
    if (!entry) {
      return;
    }
    if (typeof entry === "string") {
      servers.push({ urls: entry });
    } else if (entry.urls) {
      servers.push(entry as RTCIceServer);
    }
  });
  return servers;
}

export function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const handler = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", handler);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", handler);
  });
}

export function applyH264Preference(
  transceiver: RTCRtpTransceiver,
  deviceId?: string,
): void {
  if (!transceiver.setCodecPreferences) {
    return;
  }
  const capabilities = RTCRtpReceiver.getCapabilities?.("video") || null;
  const codecList = (capabilities?.codecs || []) as RtpCodecCapabilityExtended[];
  if (!codecList.length) {
    return;
  }
  const preferred: RtpCodecCapabilityExtended[] = [];
  const rest: RtpCodecCapabilityExtended[] = [];
  const h264Payloads = new Set<number>();
  codecList.forEach((codec) => {
    if (codec.mimeType?.toLowerCase() === "video/h264") {
      preferred.push(codec);
      if (typeof codec.payloadType === "number") {
        h264Payloads.add(codec.payloadType);
      }
    }
  });
  codecList.forEach((codec) => {
    const apt = codec.parameters?.apt;
    if (
      codec.mimeType?.toLowerCase() === "video/rtx" &&
      typeof apt === "number" &&
      h264Payloads.has(apt)
    ) {
      preferred.push(codec);
    }
  });
  codecList.forEach((codec) => {
    if (!preferred.includes(codec)) {
      rest.push(codec);
    }
  });
  if (!preferred.length) {
    return;
  }
  transceiver.setCodecPreferences([...preferred, ...rest]);
  if (deviceId) {
    console.log(
      "[webrtc] codec preference",
      deviceId,
      preferred.map((codec) => codec.mimeType),
    );
  }
}
