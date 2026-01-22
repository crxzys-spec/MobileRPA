<template>
  <section class="control">
    <div class="control-top">
      <label class="field control-device">
        <span>{{ t("device.label") }}</span>
        <select v-model="deviceId">
          <option value="">{{ t("device.select") }}</option>
          <option
            v-for="device in props.devices"
            :key="device.id"
            :value="device.id"
            :disabled="deviceUnavailable(device)"
          >
            {{ deviceLabel(device) }}
          </option>
        </select>
      </label>
      <span class="control-status" :class="{ active: deviceId }">
        {{ props.statusMessage }}
      </span>
    </div>
    <div class="control-groups">
      <div class="control-group">
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canToggleStream"
          :aria-label="streamToggleLabel"
          :title="streamToggleLabel"
          @click="emitStreamToggle"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <polygon
              v-if="!streamActive"
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
          v-if="canSwitchToMjpeg"
          class="chip icon-btn"
          type="button"
          :disabled="!canToggleStream"
          :aria-label="t('live.switchToMjpeg')"
          :title="t('live.switchToMjpeg')"
          @click="emitStreamMjpeg"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="4" y="7" width="16" height="10" rx="2" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </button>
        <button
          v-else-if="canSwitchToWebrtc"
          class="chip icon-btn"
          type="button"
          :disabled="!canToggleStream"
          :aria-label="t('live.switchToWebrtc')"
          :title="t('live.switchToWebrtc')"
          @click="emitStreamWebrtc"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 10a10 10 0 0 1 14 0" />
            <path d="M8 13a6 6 0 0 1 8 0" />
            <path d="M11 16a2 2 0 0 1 2 0" />
            <circle class="icon-fill" cx="12" cy="19" r="1.5" />
          </svg>
        </button>
      </div>
      <div class="control-group stream-session">
        <span
          class="stream-session-dot"
          :class="streamSessionStateClass"
          :title="streamSessionStateLabel"
        ></span>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canEditStreamConfig"
          :aria-label="t('streamSession.video')"
          :title="t('streamSession.video')"
          :class="{ 'is-active': streamConfig.video, 'is-off': !streamConfig.video }"
          @click="toggleStreamFlag('video')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="4" y="7" width="13" height="10" rx="2" />
            <polygon class="icon-fill" points="17,9 21,12 17,15" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canEditStreamConfig"
          :aria-label="t('streamSession.audio')"
          :title="t('streamSession.audio')"
          :class="{ 'is-active': streamConfig.audio, 'is-off': !streamConfig.audio }"
          @click="toggleStreamFlag('audio')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9v6h4l5 4V5l-5 4H4z" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canEditStreamConfig"
          :aria-label="t('streamSession.control')"
          :title="t('streamSession.control')"
          :class="{ 'is-active': streamConfig.control, 'is-off': !streamConfig.control }"
          @click="toggleStreamFlag('control')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="3" x2="12" y2="7" />
            <line x1="12" y1="17" x2="12" y2="21" />
            <line x1="3" y1="12" x2="7" y2="12" />
            <line x1="17" y1="12" x2="21" y2="12" />
          </svg>
        </button>
        <span class="stream-session-divider" aria-hidden="true"></span>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canStartStreamSession"
          :aria-label="t('streamSession.start')"
          :title="t('streamSession.start')"
          :class="{ 'is-active': streamSessionRunning, 'is-off': !streamSessionRunning }"
          @click="emitStreamSessionStart"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <polygon class="icon-fill" points="8,5 19,12 8,19" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canStopStreamSession"
          :aria-label="t('streamSession.stop')"
          :title="t('streamSession.stop')"
          :class="{ 'is-active': streamSessionRunning, 'is-off': !streamSessionRunning }"
          @click="emitStreamSessionStop"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect class="icon-fill" x="7" y="7" width="10" height="10" rx="2" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canRestartStreamSession"
          :aria-label="t('streamSession.restart')"
          :title="t('streamSession.restart')"
          :class="{ 'is-active': streamSessionRunning, 'is-off': !streamSessionRunning }"
          @click="emitStreamSessionRestart"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M16 5v4h4" />
            <path d="M20 9a8 8 0 1 1-2.34-5.66" />
          </svg>
        </button>
      </div>
      <div class="control-group">
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.back')"
          :title="t('device.back')"
          @click="emitCommand('back')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <polyline points="12 6 6 12 12 18" />
            <line x1="6" y1="12" x2="18" y2="12" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.home')"
          :title="t('device.home')"
          @click="emitCommand('home')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 11l8-6 8 6" />
            <path d="M6 10v9a1 1 0 0 0 1 1h4v-5h2v5h4a1 1 0 0 0 1-1v-9" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.recents')"
          :title="t('device.recents')"
          @click="emitCommand('recent')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="6" y="5" width="12" height="14" rx="2" />
          </svg>
        </button>
      </div>
      <div class="control-group">
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.power')"
          :title="t('device.power')"
          @click="emitKey('KEYCODE_POWER')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <line x1="12" y1="3" x2="12" y2="11" />
            <path d="M7 8a6 6 0 1 0 10 0" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.volumeUp')"
          :title="t('device.volumeUp')"
          @click="emitKey('KEYCODE_VOLUME_UP')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9v6h4l5 4V5l-5 4H4z" />
            <line x1="17" y1="10" x2="17" y2="14" />
            <line x1="15" y1="12" x2="19" y2="12" />
          </svg>
        </button>
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId || !inputEnabled"
          :aria-label="t('device.volumeDown')"
          :title="t('device.volumeDown')"
          @click="emitKey('KEYCODE_VOLUME_DOWN')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9v6h4l5 4V5l-5 4H4z" />
            <line x1="15" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
      <div class="control-group control-input">
        <input
          v-model="inputText"
          class="control-input-field"
          type="text"
          :disabled="!deviceId || !inputEnabled"
          :placeholder="t('device.inputPlaceholder')"
          :aria-label="t('device.inputPlaceholder')"
          @keydown.enter.prevent="sendInputText"
        />
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!canSendInput"
          :aria-label="t('device.inputSend')"
          :title="t('device.inputSend')"
          @click="sendInputText"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              class="icon-fill"
              d="M4 4l16 8-16 8 3-8-3-8z"
            />
          </svg>
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type {
  Device,
  DeviceCommandRequest,
  DeviceCommandType,
  StreamSessionConfigRequest,
  StreamSessionStatus,
} from "../api/types";

const props = defineProps<{
  devices: Device[];
  statusMessage: string;
  streamActive?: boolean;
  streamMode?: "webrtc" | "mjpeg" | null;
  streamSession?: StreamSessionStatus | null;
  mjpegAvailable?: boolean;
  inputEnabled?: boolean;
}>();

const { t } = useI18n();

const deviceId = defineModel<string>("deviceId", { required: true });

const emit = defineEmits<{
  (e: "command", deviceId: string, payload: DeviceCommandRequest): void;
  (e: "stream-toggle", deviceId: string): void;
  (e: "stream-mjpeg", deviceId: string): void;
  (e: "stream-webrtc", deviceId: string): void;
  (e: "stream-session-start", deviceId: string): void;
  (e: "stream-session-stop", deviceId: string): void;
  (e: "stream-session-restart", deviceId: string): void;
  (e: "stream-session-config", deviceId: string, payload: StreamSessionConfigRequest): void;
}>();

function deviceUnavailable(device?: Device | null) {
  if (!device) {
    return false;
  }
  if (isClientOffline(device)) {
    return true;
  }
  return Boolean(device.status && device.status !== "device");
}

function normalizeClientStatus(value?: string) {
  return (value || "unknown").toString().toLowerCase();
}

function isClientOffline(device?: Device | null) {
  return normalizeClientStatus(device?.client_status) === "offline";
}

function deviceLabel(device: Device) {
  if (device.status && device.status !== "device") {
    return `${device.id} (${device.status})`;
  }
  if (isClientOffline(device)) {
    return `${device.id} (${t("status.offline")})`;
  }
  return device.id;
}

const selectedDevice = computed(
  () => props.devices.find((device) => device.id === deviceId.value) || null,
);
const streamActive = computed(() => Boolean(props.streamActive));
const streamMode = computed(() => props.streamMode || null);
const mjpegAvailable = computed(() => props.mjpegAvailable !== false);
const canToggleStream = computed(
  () => Boolean(deviceId.value) && !deviceUnavailable(selectedDevice.value),
);
const canChangeStream = computed(() =>
  Boolean(deviceId.value) && !deviceUnavailable(selectedDevice.value),
);
const canSwitchToMjpeg = computed(
  () => mjpegAvailable.value && streamActive.value && streamMode.value === "webrtc",
);
const canSwitchToWebrtc = computed(
  () => streamActive.value && streamMode.value === "mjpeg",
);
const streamToggleLabel = computed(() =>
  streamActive.value ? t("live.stop") : t("live.start"),
);
const streamSession = computed(() => props.streamSession || null);
const inputEnabled = computed(
  () => props.inputEnabled !== false && !deviceUnavailable(selectedDevice.value),
);
const clientOffline = computed(() => isClientOffline(selectedDevice.value));
const streamConfig = computed(() => ({
  video: streamSession.value?.config?.video ?? true,
  audio: streamSession.value?.config?.audio ?? false,
  control: streamSession.value?.config?.control ?? true,
}));
const streamSessionStatus = computed(
  () =>
    clientOffline.value
      ? "offline"
      : (streamSession.value?.status || "stopped").toLowerCase(),
);
const streamSessionRunning = computed(
  () => streamSessionStatus.value === "running",
);
const streamSessionStarting = computed(
  () => streamSessionStatus.value === "starting",
);
const streamSessionStopping = computed(
  () => streamSessionStatus.value === "stopping",
);
const streamSessionConnected = computed(
  () =>
    streamSessionRunning.value ||
    streamSessionStarting.value ||
    streamSessionStopping.value,
);
const streamSessionError = computed(
  () => streamSessionStatus.value === "error",
);
const canEditStreamConfig = computed(
  () =>
    Boolean(deviceId.value) &&
    !streamSessionConnected.value &&
    !deviceUnavailable(selectedDevice.value),
);
const canStartStreamSession = computed(
  () => canChangeStream.value && !streamSessionConnected.value,
);
const canStopStreamSession = computed(
  () => canChangeStream.value && streamSessionConnected.value,
);
const canRestartStreamSession = computed(
  () => canChangeStream.value && streamSessionConnected.value,
);
const streamSessionStateClass = computed(() => {
  if (clientOffline.value) {
    return "offline";
  }
  if (streamSessionError.value) {
    return "error";
  }
  if (streamSessionRunning.value) {
    return "running";
  }
  if (streamSessionStarting.value) {
    return "starting";
  }
  if (streamSessionStopping.value) {
    return "stopping";
  }
  return "stopped";
});
const streamSessionStateLabel = computed(() => {
  if (clientOffline.value) {
    return t("session.offline");
  }
  if (streamSessionError.value) {
    return t("streamSession.status.error");
  }
  if (streamSessionRunning.value) {
    return t("streamSession.status.running");
  }
  if (streamSessionStarting.value) {
    return t("streamSession.status.starting");
  }
  if (streamSessionStopping.value) {
    return t("streamSession.status.stopping");
  }
  return t("streamSession.status.stopped");
});
const inputText = ref("");
const canSendInput = computed(() => {
  if (!deviceId.value || !inputEnabled.value) {
    return false;
  }
  return Boolean(inputText.value.trim());
});

function emitStreamToggle() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-toggle", deviceId.value);
}

function emitStreamMjpeg() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-mjpeg", deviceId.value);
}

function emitStreamWebrtc() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-webrtc", deviceId.value);
}

function emitStreamSessionStart() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-session-start", deviceId.value);
}

function emitStreamSessionStop() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-session-stop", deviceId.value);
}

function emitStreamSessionRestart() {
  if (!deviceId.value) {
    return;
  }
  emit("stream-session-restart", deviceId.value);
}

function toggleStreamFlag(flag: "video" | "audio" | "control") {
  if (!deviceId.value || !canEditStreamConfig.value) {
    return;
  }
  const next = !streamConfig.value[flag];
  emit("stream-session-config", deviceId.value, { [flag]: next });
}

function emitCommand(type: DeviceCommandType) {
  if (!deviceId.value || !inputEnabled.value) {
    return;
  }
  emit("command", deviceId.value, { type });
}

function emitKey(keycode: string) {
  if (!deviceId.value || !inputEnabled.value) {
    return;
  }
  emit("command", deviceId.value, { type: "keyevent", keycode });
}

function sendInputText() {
  if (!canSendInput.value) {
    return;
  }
  const text = inputText.value;
  emit("command", deviceId.value, { type: "input_text", text });
  inputText.value = "";
}
</script>
