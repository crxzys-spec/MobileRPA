<template>
  <section class="panel live">
    <div class="panel-header">
      <h2>{{ t("live.title") }}</h2>
      <div class="panel-actions">
        <button
          class="ghost icon-btn"
          type="button"
          :aria-label="t('live.refresh')"
          :title="t('live.refresh')"
          @click="emit('refresh')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 12a8 8 0 1 1-2.34-5.66" />
            <polyline points="20 5 20 12 13 12" />
          </svg>
        </button>
      </div>
    </div>
    <div class="live-grid" :class="density">
      <div v-if="!props.devices.length" class="empty">{{ t("live.noDevices") }}</div>
      <div
        v-for="(device, index) in props.devices"
        :key="device.id"
        class="live-card"
        :class="{
          streaming: isStreaming(device.id),
          'control-enabled': isControlEnabled(device.id),
          selected: device.id === props.selectedDeviceId,
        }"
        :style="{ animationDelay: `${index * 0.03}s` }"
        @click="emit('select', device.id)"
      >
        <div
          class="live-frame"
          :class="{ ready: hasStream(device.id) }"
          :style="frameStyle(device.id)"
        >
          <div
            v-if="density === 'compact' && !overlayHidden[device.id]"
            class="live-overlay-bar"
          >
            <span
              class="live-conn-icon"
              :class="connectionStateClass(device.id)"
              :title="connectionStateLabel(device.id)"
            ></span>
            <span class="live-overlay-text">{{ device.id }}</span>
            <span class="live-overlay-sep">•</span>
            <span class="live-overlay-text">{{ statsFps(device.id) }}</span>
          </div>
          <div class="live-placeholder" :class="{ hidden: hasStream(device.id) }">
            {{ livePlaceholder(device.id) }}
          </div>
          <video
            v-if="isWebrtc(device.id)"
            class="live-stream"
            autoplay
            muted
            playsinline
            :ref="(el) => setVideoRef(device.id, el)"
          ></video>
          <img
            v-else-if="isMjpeg(device.id)"
            class="live-stream"
            :src="mjpegSrc(device.id)"
            :alt="t('live.mjpegStream')"
            :ref="(el) => setImageRef(device.id, el)"
          />
          <div
            class="live-overlay"
            :class="{ enabled: isControlEnabled(device.id) }"
            @pointerdown="onPointerDown(device.id, $event)"
            @pointermove="onPointerMove(device.id, $event)"
            @pointerup="onPointerUp(device.id, $event)"
            @pointercancel="onPointerCancel(device.id, $event)"
            @pointerleave="onPointerCancel(device.id, $event)"
          ></div>
        </div>
        <div class="live-controls">
          <button
            class="ghost icon-btn"
            type="button"
            :aria-label="overlayButtonLabel(device.id)"
            :title="overlayButtonLabel(device.id)"
            :class="{
              'is-active': !overlayHidden[device.id],
              'is-off': overlayHidden[device.id],
            }"
            @click="toggleOverlay(device.id)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                v-if="overlayHidden[device.id]"
                d="M4 4l16 16"
              />
              <path
                d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6Z"
              />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          <button
            class="ghost icon-btn"
            type="button"
            data-action="toggle-stream"
            :disabled="deviceUnavailable(device)"
            :aria-label="streamButtonLabel(device)"
            :title="streamButtonLabel(device)"
            :class="{
              'is-active': isStreaming(device.id),
              'is-off': !isStreaming(device.id),
            }"
            @click="emit('toggle', device.id)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <polygon
                v-if="!isStreaming(device.id)"
                class="icon-fill"
                points="8,5 19,12 8,19"
              />
              <rect
                v-else
                class="icon-fill"
                x="7"
                y="7"
                width="10"
                height="10"
                rx="2"
              />
            </svg>
          </button>
          <button
            class="ghost icon-btn"
            type="button"
            :disabled="!canToggleControl(device)"
            :aria-label="controlButtonLabel(device.id)"
            :title="controlButtonLabel(device.id)"
            :class="{
              'is-active': isControlEnabled(device.id),
              'is-off': !isControlEnabled(device.id),
            }"
            @click="toggleControl(device.id)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="3" x2="12" y2="7" />
              <line x1="12" y1="17" x2="12" y2="21" />
              <line x1="3" y1="12" x2="7" y2="12" />
              <line x1="17" y1="12" x2="21" y2="12" />
              <circle
                v-if="isControlEnabled(device.id)"
                class="icon-fill"
                cx="12"
                cy="12"
                r="2"
              />
            </svg>
          </button>
          <button
            class="ghost icon-btn"
            type="button"
            :disabled="deviceUnavailable(device)"
            :aria-label="t('device.back')"
            :title="t('device.back')"
            @click="emitCommand(device.id, 'back')"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <polyline points="12 6 6 12 12 18" />
              <line x1="6" y1="12" x2="18" y2="12" />
            </svg>
          </button>
          <button
            class="ghost icon-btn"
            type="button"
            :disabled="deviceUnavailable(device)"
            :aria-label="t('device.home')"
            :title="t('device.home')"
            @click="emitCommand(device.id, 'home')"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 11l8-6 8 6" />
              <path d="M6 10v9a1 1 0 0 0 1 1h4v-5h2v5h4a1 1 0 0 0 1-1v-9" />
            </svg>
          </button>
          <button
            class="ghost icon-btn"
            type="button"
            :disabled="deviceUnavailable(device)"
            :aria-label="t('device.recents')"
            :title="t('device.recents')"
            @click="emitCommand(device.id, 'recent')"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="6" y="5" width="12" height="14" rx="2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, watch, type ComponentPublicInstance } from "vue";
import { useI18n } from "vue-i18n";

import type { Device, DeviceCommandRequest, DeviceCommandType } from "../api/types";

type LiveConnectionView = {
  stream: MediaStream | null;
  status: string;
  mode: "webrtc" | "mjpeg";
  mjpegUrl?: string;
};

type LiveStatsView = {
  bitrateKbps?: number | null;
  fps?: number | null;
  packets?: number | null;
  frames?: number | null;
  jitter?: number | null;
  width?: number | null;
  height?: number | null;
  updatedAt?: number | null;
};

type TapPayload = {
  x: number;
  y: number;
};

type SwipePayload = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  duration_ms: number;
};

const props = defineProps<{
  devices: Device[];
  liveConnections: Record<string, LiveConnectionView>;
  liveMessages: Record<string, string>;
  liveStats: Record<string, LiveStatsView>;
  selectedDeviceId?: string | null;
}>();

const emit = defineEmits<{
  (e: "refresh"): void;
  (e: "toggle", deviceId: string): void;
  (e: "select", deviceId: string): void;
  (e: "tap", deviceId: string, payload: TapPayload): void;
  (e: "swipe", deviceId: string, payload: SwipePayload): void;
  (e: "command", deviceId: string, payload: DeviceCommandRequest): void;
}>();

const { t } = useI18n();

const videoRefs = new Map<string, HTMLVideoElement>();
const imageRefs = new Map<string, HTMLImageElement>();
const attachedStreams = new Set<string>();
const controlEnabled = reactive<Record<string, boolean>>({});
const overlayHidden = reactive<Record<string, boolean>>({});
const density = "compact";
const interactions = reactive<
  Record<
    string,
    | {
        pointerId: number;
        start: TapPayload;
        last: TapPayload;
        startTime: number;
        moved: boolean;
      }
    | undefined
  >
>({});
const dragThreshold = 12;

function normalizeDeviceStatus(value?: string) {
  return (value || "unknown").toString().toLowerCase();
}

function deviceStatusLabel(value?: string) {
  const status = normalizeDeviceStatus(value);
  if (status === "device") {
    return t("status.device");
  }
  if (status === "offline") {
    return t("status.offline");
  }
  if (status === "unauthorized") {
    return t("status.unauthorized");
  }
  return t("status.unknown");
}

function deviceStatusClass(value?: string) {
  const status = normalizeDeviceStatus(value);
  if (["device", "offline", "unauthorized"].includes(status)) {
    return status;
  }
  return "unknown";
}

function deviceUnavailable(device?: Device | null) {
  return Boolean(device?.status && device.status !== "device");
}

function isControlEnabled(deviceId: string) {
  return Boolean(controlEnabled[deviceId]);
}

function canToggleControl(device?: Device | null) {
  if (!device || deviceUnavailable(device)) {
    return false;
  }
  return isStreaming(device.id);
}

function toggleControl(deviceId: string) {
  if (!isStreaming(deviceId)) {
    return;
  }
  controlEnabled[deviceId] = !controlEnabled[deviceId];
}

function controlButtonLabel(deviceId: string) {
  return isControlEnabled(deviceId) ? t("live.controlOn") : t("live.controlOff");
}

function toggleOverlay(deviceId: string) {
  overlayHidden[deviceId] = !overlayHidden[deviceId];
}

function overlayButtonLabel(deviceId: string) {
  return overlayHidden[deviceId] ? t("live.showOverlay") : t("live.hideOverlay");
}

function emitCommand(deviceId: string, type: DeviceCommandType) {
  emit("command", deviceId, { type });
}

function streamButtonLabel(device: Device) {
  if (deviceUnavailable(device)) {
    return t("live.unavailable");
  }
  return isStreaming(device.id) ? t("live.stop") : t("live.start");
}

function connectionState(deviceId: string) {
  if (hasStream(deviceId)) {
    return "connected";
  }
  if (props.liveConnections[deviceId]) {
    return "connecting";
  }
  return "offline";
}

function connectionStateClass(deviceId: string) {
  return connectionState(deviceId);
}

function connectionStateLabel(deviceId: string) {
  const state = connectionState(deviceId);
  if (state === "connected") {
    return t("live.connectionConnected");
  }
  if (state === "connecting") {
    return t("live.connectionConnecting");
  }
  return t("live.connectionOffline");
}

function hasStream(deviceId: string) {
  const connection = props.liveConnections[deviceId];
  if (!connection) {
    return false;
  }
  if (connection.mode === "mjpeg") {
    return Boolean(connection.mjpegUrl);
  }
  return Boolean(connection.stream);
}

function isStreaming(deviceId: string) {
  return Boolean(props.liveConnections[deviceId]);
}

function isMjpeg(deviceId: string) {
  return props.liveConnections[deviceId]?.mode === "mjpeg";
}

function isWebrtc(deviceId: string) {
  return props.liveConnections[deviceId]?.mode === "webrtc";
}

function mjpegSrc(deviceId: string) {
  return props.liveConnections[deviceId]?.mjpegUrl || "";
}

function livePlaceholder(deviceId: string) {
  const connection = props.liveConnections[deviceId];
  if (!connection) {
    return props.liveMessages[deviceId] || t("live.streamStopped");
  }
  if (connection.stream) {
    return "";
  }
  if (connection.mode === "mjpeg") {
    return connection.status || t("live.mjpegStream");
  }
  return connection.status || t("live.connecting");
}

function setVideoRef(deviceId: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLVideoElement) {
    videoRefs.set(deviceId, el);
    syncStreams();
    return;
  }
  videoRefs.delete(deviceId);
}

function setImageRef(deviceId: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLImageElement) {
    imageRefs.set(deviceId, el);
    return;
  }
  imageRefs.delete(deviceId);
}

function attachStream(deviceId: string, stream: MediaStream | null) {
  const video = videoRefs.get(deviceId);
  if (!video) {
    return;
  }
  if (video.srcObject !== stream) {
    video.srcObject = stream || null;
    if (stream) {
      video.play().catch(() => {});
    }
  }
}

function syncStreams() {
  const connectionIds = Object.keys(props.liveConnections);
  connectionIds.forEach((deviceId) => {
    const connection = props.liveConnections[deviceId];
    if (connection?.mode === "webrtc") {
      attachStream(deviceId, connection?.stream || null);
    } else {
      attachStream(deviceId, null);
    }
  });
  attachedStreams.forEach((deviceId) => {
    if (!props.liveConnections[deviceId]) {
      attachStream(deviceId, null);
    }
  });
  attachedStreams.clear();
  connectionIds.forEach((deviceId) => attachedStreams.add(deviceId));
  Object.keys(controlEnabled).forEach((deviceId) => {
    if (!props.liveConnections[deviceId]) {
      delete controlEnabled[deviceId];
    }
  });
}

function getSourceSize(deviceId: string) {
  const stats = props.liveStats[deviceId];
  if (stats?.width && stats?.height) {
    return { width: stats.width, height: stats.height };
  }
  const video = videoRefs.get(deviceId);
  if (video && video.videoWidth && video.videoHeight) {
    return { width: video.videoWidth, height: video.videoHeight };
  }
  const image = imageRefs.get(deviceId);
  if (image && image.naturalWidth && image.naturalHeight) {
    return { width: image.naturalWidth, height: image.naturalHeight };
  }
  return null;
}

function frameStyle(deviceId: string) {
  const source = getSourceSize(deviceId);
  if (!source) {
    return undefined;
  }
  return {
    "--frame-ratio": `${source.width} / ${source.height}`,
  };
}

function mapPoint(
  deviceId: string,
  event: PointerEvent,
): TapPayload | null {
  const source = getSourceSize(deviceId);
  if (!source) {
    return null;
  }
  const target = event.currentTarget as HTMLElement | null;
  if (!target) {
    return null;
  }
  const rect = target.getBoundingClientRect();
  if (!rect.width || !rect.height) {
    return null;
  }
  const sourceRatio = source.width / source.height;
  const rectRatio = rect.width / rect.height;
  let renderWidth = rect.width;
  let renderHeight = rect.height;
  let offsetX = 0;
  let offsetY = 0;
  if (rectRatio > sourceRatio) {
    renderHeight = rect.height;
    renderWidth = renderHeight * sourceRatio;
    offsetX = (rect.width - renderWidth) / 2;
  } else {
    renderWidth = rect.width;
    renderHeight = renderWidth / sourceRatio;
    offsetY = (rect.height - renderHeight) / 2;
  }
  if (renderWidth <= 0 || renderHeight <= 0) {
    return null;
  }
  const x = (event.clientX - rect.left - offsetX) / renderWidth;
  const y = (event.clientY - rect.top - offsetY) / renderHeight;
  const clampedX = Math.max(0, Math.min(1, x));
  const clampedY = Math.max(0, Math.min(1, y));
  return {
    x: Math.round(clampedX * (source.width - 1)),
    y: Math.round(clampedY * (source.height - 1)),
  };
}

function statsFps(deviceId: string) {
  const fps = props.liveStats[deviceId]?.fps;
  if (!Number.isFinite(fps)) {
    return t("live.statsFpsEmpty");
  }
  return `${Number(fps).toFixed(1)} fps`;
}

function onPointerDown(deviceId: string, event: PointerEvent) {
  if (!isControlEnabled(deviceId)) {
    return;
  }
  if (event.button !== 0) {
    return;
  }
  const point = mapPoint(deviceId, event);
  if (!point) {
    return;
  }
  const target = event.currentTarget as HTMLElement | null;
  if (target) {
    target.setPointerCapture(event.pointerId);
  }
  interactions[deviceId] = {
    pointerId: event.pointerId,
    start: point,
    last: point,
    startTime: performance.now(),
    moved: false,
  };
  event.preventDefault();
}

function onPointerMove(deviceId: string, event: PointerEvent) {
  const state = interactions[deviceId];
  if (!state || state.pointerId !== event.pointerId) {
    return;
  }
  const point = mapPoint(deviceId, event);
  if (!point) {
    return;
  }
  state.last = point;
  const dx = point.x - state.start.x;
  const dy = point.y - state.start.y;
  if (Math.hypot(dx, dy) >= dragThreshold) {
    state.moved = true;
  }
  event.preventDefault();
}

function onPointerUp(deviceId: string, event: PointerEvent) {
  const state = interactions[deviceId];
  if (!state || state.pointerId !== event.pointerId) {
    return;
  }
  const point = mapPoint(deviceId, event) || state.last;
  const dx = point.x - state.start.x;
  const dy = point.y - state.start.y;
  const durationMs = Math.min(
    1200,
    Math.max(80, Math.round(performance.now() - state.startTime)),
  );
  if (state.moved && Math.hypot(dx, dy) >= dragThreshold) {
    emit("swipe", deviceId, {
      x1: state.start.x,
      y1: state.start.y,
      x2: point.x,
      y2: point.y,
      duration_ms: durationMs,
    });
  } else {
    emit("tap", deviceId, { x: state.start.x, y: state.start.y });
  }
  interactions[deviceId] = undefined;
  event.preventDefault();
}

function onPointerCancel(deviceId: string, event: PointerEvent) {
  const state = interactions[deviceId];
  if (!state || state.pointerId !== event.pointerId) {
    return;
  }
  interactions[deviceId] = undefined;
  event.preventDefault();
}

watch(
  () => props.liveConnections,
  () => {
    syncStreams();
  },
  { deep: true, immediate: true },
);

onBeforeUnmount(() => {
  videoRefs.clear();
  imageRefs.clear();
  attachedStreams.clear();
  Object.keys(controlEnabled).forEach((key) => delete controlEnabled[key]);
  Object.keys(overlayHidden).forEach((key) => delete overlayHidden[key]);
});
</script>
