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
            {{ device.status ? `${device.id} (${device.status})` : device.id }}
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
      <div class="control-group">
        <button
          class="chip icon-btn"
          type="button"
          :disabled="!deviceId"
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
          :disabled="!deviceId"
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
          :disabled="!deviceId"
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
          :disabled="!deviceId"
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
          :disabled="!deviceId"
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
          :disabled="!deviceId"
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
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type {
  Device,
  DeviceCommandRequest,
  DeviceCommandType,
} from "../api/types";

const props = defineProps<{
  devices: Device[];
  statusMessage: string;
  streamActive?: boolean;
  streamMode?: "webrtc" | "mjpeg" | null;
}>();

const { t } = useI18n();

const deviceId = defineModel<string>("deviceId", { required: true });

const emit = defineEmits<{
  (e: "command", deviceId: string, payload: DeviceCommandRequest): void;
  (e: "stream-toggle", deviceId: string): void;
  (e: "stream-mjpeg", deviceId: string): void;
  (e: "stream-webrtc", deviceId: string): void;
}>();

function deviceUnavailable(device?: Device | null) {
  return Boolean(device?.status && device.status !== "device");
}

const selectedDevice = computed(
  () => props.devices.find((device) => device.id === deviceId.value) || null,
);
const streamActive = computed(() => Boolean(props.streamActive));
const streamMode = computed(() => props.streamMode || null);
const canToggleStream = computed(
  () => Boolean(deviceId.value) && !deviceUnavailable(selectedDevice.value),
);
const canSwitchToMjpeg = computed(
  () => streamActive.value && streamMode.value === "webrtc",
);
const canSwitchToWebrtc = computed(
  () => streamActive.value && streamMode.value === "mjpeg",
);
const streamToggleLabel = computed(() =>
  streamActive.value ? t("live.stop") : t("live.start"),
);

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

function emitCommand(type: DeviceCommandType) {
  if (!deviceId.value) {
    return;
  }
  emit("command", deviceId.value, { type });
}

function emitKey(keycode: string) {
  if (!deviceId.value) {
    return;
  }
  emit("command", deviceId.value, { type: "keyevent", keycode });
}
</script>
