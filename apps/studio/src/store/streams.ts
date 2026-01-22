import { defineStore } from "pinia";
import { markRaw, reactive, ref } from "vue";

import type {
  Device,
  StreamSessionConfigRequest,
  StreamSessionStatus,
  WebrtcConfig,
} from "../api/types";
import { apiUrl } from "../client/http";
import {
  applyH264Preference,
  buildIceServers,
  waitForIceGathering,
} from "../service/webrtc";
import { streamsService } from "../service/streams";
import { useAppStore } from "./app";

type StreamMode = "webrtc" | "mjpeg";

interface LiveConnection {
  pc: RTCPeerConnection | null;
  stream: MediaStream | null;
  status: string;
  mode: StreamMode;
  mjpegUrl?: string;
  fallbackTimerId?: number | null;
  statsTimerId?: number | null;
}

interface LiveStats {
  bitrateKbps?: number | null;
  fps?: number | null;
  packets?: number | null;
  frames?: number | null;
  jitter?: number | null;
  width?: number | null;
  height?: number | null;
  updatedAt?: number | null;
}

export const useStreamsStore = defineStore("streams", () => {
  const app = useAppStore();

  const webrtcConfig = ref<WebrtcConfig | null>(null);
  const liveConnections = reactive<Record<string, LiveConnection>>({});
  const liveMessages = reactive<Record<string, string>>({});
  const liveStats = reactive<Record<string, LiveStats>>({});
  const streamSessions = reactive<Record<string, StreamSessionStatus>>({});
  const mjpegAvailable = ref(true);
  const streamSessionsAvailable = ref<boolean | null>(null);
  const statsCache = new Map<string, { bytes: number; frames: number; ts: number }>();
  const liveRetryCount = 2;
  const liveRetryDelayMs = 800;
  const fallbackTimeoutMs = 4000;

  async function ensureWebRTCConfig(): Promise<WebrtcConfig> {
    if (webrtcConfig.value) {
      return webrtcConfig.value;
    }
    webrtcConfig.value = await streamsService.getWebRTCConfig();
    if (typeof webrtcConfig.value.mjpeg_available === "boolean") {
      mjpegAvailable.value = webrtcConfig.value.mjpeg_available;
    }
    return webrtcConfig.value;
  }

  function errorStatus(error: unknown): number | null {
    if (!error || typeof error !== "object") {
      return null;
    }
    const status = (error as { status?: number }).status;
    return typeof status === "number" ? status : null;
  }

  function isNotAvailable(error: unknown): boolean {
    const status = errorStatus(error);
    if (status === 501) {
      return true;
    }
    const message =
      error && typeof error === "object" && "message" in error
        ? String((error as { message?: string }).message || "")
        : "";
    return message.toLowerCase().includes("not available");
  }

  function buildMjpegUrl(deviceId: string): string {
    const base = `/api/stream/${encodeURIComponent(deviceId)}.mjpg`;
    return apiUrl(`${base}?t=${Date.now()}`);
  }

  function isConnectionActive(deviceId: string, pc: RTCPeerConnection): boolean {
    return liveConnections[deviceId]?.pc === pc;
  }

  function stopLiveStream(deviceId: string, message?: string) {
    const connection = liveConnections[deviceId];
    if (connection?.fallbackTimerId) {
      window.clearTimeout(connection.fallbackTimerId);
    }
    if (connection?.statsTimerId) {
      window.clearInterval(connection.statsTimerId);
    }
    if (connection?.pc) {
      connection.pc.ontrack = null;
      connection.pc.onconnectionstatechange = null;
      connection.pc.close();
    }
    delete liveConnections[deviceId];
    delete liveStats[deviceId];
    statsCache.delete(deviceId);
    if (message) {
      liveMessages[deviceId] = message;
    } else {
      delete liveMessages[deviceId];
    }
  }

  function shouldStopForSession(session?: StreamSessionStatus | null) {
    if (!session) {
      return false;
    }
    const status = (session.status || "stopped").toLowerCase();
    if (status === "running" || status === "starting") {
      return session.config?.video === false;
    }
    return true;
  }

  function sessionStopMessage(session?: StreamSessionStatus | null) {
    if (!session) {
      return "Stream stopped";
    }
    const status = (session.status || "stopped").toLowerCase();
    if (status === "error") {
      return "Stream error";
    }
    return "Stream stopped";
  }

  function reconcileLiveWithSession(
    deviceId: string,
    session?: StreamSessionStatus | null,
  ) {
    if (!liveConnections[deviceId]) {
      return;
    }
    if (!shouldStopForSession(session)) {
      return;
    }
    stopLiveStream(deviceId, sessionStopMessage(session));
  }

  function getStreamSession(deviceId: string): StreamSessionStatus | null {
    return streamSessions[deviceId] || null;
  }

  async function refreshStreamSession(deviceId: string) {
    app.clearError();
    try {
      const session = await streamsService.getStreamSession(deviceId);
      streamSessions[deviceId] = session;
      streamSessionsAvailable.value = true;
      reconcileLiveWithSession(deviceId, session);
      return session;
    } catch (error) {
      if (isNotAvailable(error)) {
        streamSessionsAvailable.value = false;
        return null;
      }
      app.setError(error);
      throw error;
    }
  }

  async function ensureStreamSessionRunning(deviceId: string) {
    if (streamSessionsAvailable.value === false) {
      return;
    }
    try {
      let session = streamSessions[deviceId];
      if (!session) {
        try {
          session = await streamsService.getStreamSession(deviceId);
          streamSessions[deviceId] = session;
        } catch (error) {
          if (isNotAvailable(error)) {
            streamSessionsAvailable.value = false;
            return;
          }
          session = null;
        }
      }
      streamSessionsAvailable.value = true;
      const running = session?.status?.toLowerCase() === "running";
      const videoEnabled = session?.config?.video ?? true;
      if (running && videoEnabled) {
        return;
      }
      const configOverride = videoEnabled ? undefined : { video: true };
      const started = running
        ? await streamsService.restartStreamSession(deviceId, configOverride)
        : await streamsService.startStreamSession(deviceId, configOverride);
      streamSessions[deviceId] = started;
      streamSessionsAvailable.value = true;
    } catch (error) {
      if (isNotAvailable(error)) {
        streamSessionsAvailable.value = false;
        return;
      }
      throw error;
    }
  }

  async function startStreamSession(
    deviceId: string,
    config?: StreamSessionConfigRequest,
  ) {
    app.clearError();
    try {
      const session = await streamsService.startStreamSession(deviceId, config);
      streamSessions[deviceId] = session;
      streamSessionsAvailable.value = true;
      reconcileLiveWithSession(deviceId, session);
      return session;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function stopStreamSession(deviceId: string) {
    app.clearError();
    try {
      const session = await streamsService.stopStreamSession(deviceId);
      streamSessions[deviceId] = session;
      streamSessionsAvailable.value = true;
      reconcileLiveWithSession(deviceId, session);
      return session;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function restartStreamSession(
    deviceId: string,
    config?: StreamSessionConfigRequest,
  ) {
    app.clearError();
    try {
      const session = await streamsService.restartStreamSession(deviceId, config);
      streamSessions[deviceId] = session;
      streamSessionsAvailable.value = true;
      reconcileLiveWithSession(deviceId, session);
      return session;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function updateStreamSessionConfig(
    deviceId: string,
    config: StreamSessionConfigRequest,
  ) {
    app.clearError();
    try {
      const session = await streamsService.updateStreamSessionConfig(
        deviceId,
        config,
      );
      streamSessions[deviceId] = session;
      streamSessionsAvailable.value = true;
      reconcileLiveWithSession(deviceId, session);
      return session;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  function startMjpegStream(deviceId: string, reason?: string) {
    if (!mjpegAvailable.value) {
      stopLiveStream(deviceId, reason || "MJPEG unavailable");
      return;
    }
    const connection: LiveConnection = reactive({
      pc: null,
      stream: null,
      status: reason || "MJPEG stream",
      mode: "mjpeg",
      mjpegUrl: buildMjpegUrl(deviceId),
      fallbackTimerId: null,
      statsTimerId: null,
    });
    liveConnections[deviceId] = connection;
    delete liveStats[deviceId];
    statsCache.delete(deviceId);
    liveMessages[deviceId] = "";
  }

  function useMjpegFallback(deviceId: string, reason?: string) {
    if (liveConnections[deviceId]?.mode === "mjpeg") {
      return;
    }
    if (!mjpegAvailable.value) {
      stopLiveStream(deviceId, reason || "WebRTC failed");
      return;
    }
    stopLiveStream(deviceId);
    startMjpegStream(deviceId, reason || "MJPEG fallback");
  }

  function sleep(ms: number) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function updateStats(deviceId: string, pc: RTCPeerConnection) {
    if (!isConnectionActive(deviceId, pc)) {
      return;
    }
    pc.getStats()
      .then((report) => {
        let inbound: RTCInboundRtpStreamStats | null = null;
        report.forEach((stat) => {
          if (stat.type === "inbound-rtp" && stat.kind === "video") {
            inbound = stat as RTCInboundRtpStreamStats;
          }
        });
        if (!inbound) {
          return;
        }
        const inboundAny = inbound as RTCInboundRtpStreamStats & {
          framesReceived?: number;
          framesRendered?: number;
          frameWidth?: number;
          frameHeight?: number;
        };
        const bytes = inboundAny.bytesReceived || 0;
        const frames =
          inboundAny.framesDecoded ??
          inboundAny.framesReceived ??
          inboundAny.framesRendered ??
          0;
        const now = inbound.timestamp || performance.now();
        const prev = statsCache.get(deviceId);
        let bitrateKbps: number | null = null;
        let fps: number | null = null;
        if (prev) {
          const dtMs = now - prev.ts;
          if (dtMs > 0) {
            bitrateKbps = ((bytes - prev.bytes) * 8) / dtMs;
            fps = (frames - prev.frames) * 1000 / dtMs;
          }
        }
        statsCache.set(deviceId, { bytes, frames, ts: now });
        liveStats[deviceId] = {
          bitrateKbps: bitrateKbps ?? null,
          fps: fps ?? null,
          packets: inbound.packetsReceived ?? null,
          frames:
            inboundAny.framesDecoded ?? inboundAny.framesReceived ?? null,
          jitter: inbound.jitter ?? null,
          width: inboundAny.frameWidth ?? null,
          height: inboundAny.frameHeight ?? null,
          updatedAt: Date.now(),
        };
      })
      .catch(() => {});
  }

  function startStatsPolling(deviceId: string, pc: RTCPeerConnection) {
    const connection = liveConnections[deviceId];
    if (!connection || connection.statsTimerId) {
      return;
    }
    connection.statsTimerId = window.setInterval(() => {
      updateStats(deviceId, pc);
    }, 1000);
  }

  async function startWebRTCStreamOnce(deviceId: string) {
    app.clearError();
    try {
      const config = await ensureWebRTCConfig();
      await ensureStreamSessionRunning(deviceId);
      const pc = markRaw(
        new RTCPeerConnection({ iceServers: buildIceServers(config) }),
      );
      const connection: LiveConnection = reactive({
        pc,
        stream: null,
        status: "Connecting...",
        mode: "webrtc",
        mjpegUrl: undefined,
        fallbackTimerId: null,
        statsTimerId: null,
      });
      liveConnections[deviceId] = connection;
      liveMessages[deviceId] = "";

      const transceiver = pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });
      applyH264Preference(transceiver, deviceId);

      pc.ontrack = (event) => {
        if (!isConnectionActive(deviceId, pc)) {
          return;
        }
        const incoming = event.streams && event.streams[0];
        const existing = connection.stream;
        const stream = existing || incoming || new MediaStream();
        if (incoming && incoming !== stream) {
          incoming.getTracks().forEach((track) => {
            if (!stream.getTracks().some((item) => item.id === track.id)) {
              stream.addTrack(track);
            }
          });
        }
        if (!stream.getTracks().some((track) => track.id === event.track.id)) {
          stream.addTrack(event.track);
        }
        connection.stream = markRaw(stream);
        connection.status = "Connected";
        startStatsPolling(deviceId, pc);
        if (connection.fallbackTimerId) {
          window.clearTimeout(connection.fallbackTimerId);
          connection.fallbackTimerId = null;
        }
      };
      pc.onconnectionstatechange = () => {
        if (!isConnectionActive(deviceId, pc)) {
          return;
        }
        if (pc.connectionState === "connected") {
          connection.status = "Connected";
          return;
        }
        if (
          pc.connectionState === "failed" ||
          pc.connectionState === "disconnected"
        ) {
          useMjpegFallback(deviceId, "WebRTC failed");
        }
        if (pc.connectionState === "closed") {
          stopLiveStream(deviceId);
        }
      };
      pc.onicecandidate = (event) => {
        const candidate = event.candidate ? event.candidate.candidate : null;
        console.log("[webrtc] ice candidate", deviceId, candidate);
      };
      pc.onicecandidateerror = (event) => {
        console.log("[webrtc] ice candidate error", deviceId, event);
      };
      pc.oniceconnectionstatechange = () => {
        console.log("[webrtc] ice state", deviceId, pc.iceConnectionState);
      };
      pc.onicegatheringstatechange = () => {
        console.log("[webrtc] ice gathering", deviceId, pc.iceGatheringState);
      };
      pc.onsignalingstatechange = () => {
        console.log("[webrtc] signaling", deviceId, pc.signalingState);
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      console.log("[webrtc] offer", deviceId, offer);
      await waitForIceGathering(pc);
      if (!isConnectionActive(deviceId, pc)) {
        return;
      }
      const local = pc.localDescription;
      if (!local) {
        throw new Error("missing local description");
      }
      const answer = await streamsService.sendOffer({
        device_id: deviceId,
        sdp: local.sdp || "",
        type: local.type || "offer",
      });
      if (!isConnectionActive(deviceId, pc)) {
        return;
      }
      console.log("[webrtc] answer", deviceId, answer);
      await pc.setRemoteDescription(answer);
      const receiver = pc.getTransceivers?.()[0]?.receiver;
      if (receiver?.getParameters) {
        console.log(
          "[webrtc] negotiated codecs",
          deviceId,
          receiver.getParameters().codecs,
        );
      }

      connection.fallbackTimerId = window.setTimeout(() => {
        if (!isConnectionActive(deviceId, pc)) {
          return;
        }
        if (!connection.stream) {
          useMjpegFallback(deviceId, "No frames");
        }
      }, fallbackTimeoutMs);
    } catch (error) {
      stopLiveStream(deviceId, "Stream error");
      app.setError(error);
      throw error;
    }
  }

  async function startWebRTCStream(deviceId: string) {
    for (let attempt = 0; attempt < liveRetryCount; attempt += 1) {
      try {
        await startWebRTCStreamOnce(deviceId);
        return;
      } catch (error) {
        if (attempt >= liveRetryCount - 1) {
          startMjpegStream(deviceId, "WebRTC failed, using MJPEG");
          return;
        }
        liveMessages[deviceId] = "Retrying...";
        await sleep(liveRetryDelayMs);
      }
    }
  }

  async function toggleLiveStream(deviceId: string) {
    if (liveConnections[deviceId]) {
      stopLiveStream(deviceId);
      return;
    }
    await startWebRTCStream(deviceId);
  }

  function useMjpegStream(deviceId: string) {
    if (!mjpegAvailable.value) {
      liveMessages[deviceId] = "MJPEG unavailable";
      return;
    }
    stopLiveStream(deviceId);
    startMjpegStream(deviceId, "Manual MJPEG");
  }

  async function retryWebRTCStream(deviceId: string) {
    stopLiveStream(deviceId);
    await startWebRTCStream(deviceId);
  }

  function syncDevices(devices: Device[]) {
    const deviceIds = new Set(devices.map((device) => device.id));
    Object.keys(liveConnections).forEach((deviceId) => {
      if (!deviceIds.has(deviceId)) {
        stopLiveStream(deviceId, "Stream stopped");
      }
    });
    Object.keys(streamSessions).forEach((deviceId) => {
      if (!deviceIds.has(deviceId)) {
        delete streamSessions[deviceId];
      }
    });
  }

  function cleanup() {
    Object.keys(liveConnections).forEach((deviceId) => {
      stopLiveStream(deviceId);
    });
    Object.keys(streamSessions).forEach((deviceId) => {
      delete streamSessions[deviceId];
    });
    streamSessionsAvailable.value = null;
  }

  return {
    webrtcConfig,
    mjpegAvailable,
    liveConnections,
    liveMessages,
    liveStats,
    streamSessions,
    stopLiveStream,
    startWebRTCStream,
    toggleLiveStream,
    ensureWebRTCConfig,
    syncDevices,
    useMjpegStream,
    retryWebRTCStream,
    refreshStreamSession,
    startStreamSession,
    stopStreamSession,
    restartStreamSession,
    updateStreamSessionConfig,
    getStreamSession,
    cleanup,
  };
});
