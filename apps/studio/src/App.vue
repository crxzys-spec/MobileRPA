<template>
  <div
    class="app"
    :class="{ 'rail-collapsed': railCollapsed, resizing: resizing || stageConsoleResizing }"
    :style="{
      '--rail-width': railCollapsed ? '0px' : `${railWidth}px`,
      '--splitter-width': railCollapsed ? '0px' : '12px',
    }"
  >
    <header class="app-header">
      <div class="app-header-left">
        <StudioBrand :collapsed="railCollapsed" @toggle="toggleRail" />
      </div>
      <div class="app-header-right">
        <button
          class="ghost icon-btn settings-btn"
          type="button"
          :aria-label="t('app.settings')"
          :title="t('app.settings')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <line x1="4" y1="7" x2="20" y2="7" />
            <circle cx="9" cy="7" r="2" />
            <line x1="4" y1="17" x2="20" y2="17" />
            <circle cx="15" cy="17" r="2" />
          </svg>
        </button>
        <button
          class="ghost icon-btn"
          type="button"
          :aria-label="languageToggleLabel"
          :title="languageToggleLabel"
          @click="toggleLanguage"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18" />
            <path d="M12 3a12 12 0 0 1 0 18" />
            <path d="M12 3a12 12 0 0 0 0 18" />
          </svg>
        </button>
        <div class="app-avatar" aria-hidden="true">U</div>
      </div>
    </header>

    <aside v-show="!railCollapsed" class="tool-rail">
      <div class="tool-stack">
        <div class="tool-scroll">
          <RunTimeline
            :runs="runs"
            :currentRun="currentRun"
            :currentStep="currentStep"
            :selectedRunId="selectedRunId"
            :steps="steps"
            :selectedStepId="selectedStepId"
            :decisionText="decisionText"
            :promptText="promptText"
            :responseText="responseText"
            :contextText="contextText"
            :verificationText="verificationText"
            @select-run="selectRun"
            @select-step="selectStep"
          />
        </div>
        <div class="tool-footer">
          <RunConsole
            v-model:form="form"
            :devices="devices"
            :runSubmitting="runSubmitting"
            :runStatus="runStatus"
            @submit="handleRunSubmit"
            @stop="handleStopRun"
          />
        </div>
      </div>
    </aside>

    <div
      v-show="!railCollapsed"
      class="splitter"
      :class="{ dragging: resizing, disabled: railCollapsed }"
      role="separator"
      aria-orientation="vertical"
      @pointerdown="startResize"
    ></div>

    <main class="stage" :class="{ 'console-collapsed': stageConsoleCollapsed }">
      <div class="stage-wall">
        <LiveDevices
          :devices="devices"
          :liveConnections="liveConnections"
          :liveMessages="liveMessages"
          :liveStats="liveStats"
          :selectedDeviceId="controlDeviceId"
          :inputAvailable="inputAvailableByDevice"
          @refresh="refreshDevices"
          @toggle="toggleLiveStream"
          @command="handleDeviceCommand"
          @select="handleLiveSelect"
        />
      </div>

      <div
        class="stage-splitter"
        :class="{ dragging: stageConsoleResizing, disabled: stageConsoleCollapsed }"
        role="separator"
        aria-orientation="horizontal"
        @pointerdown="startStageResize"
      ></div>

      <section
        class="panel stage-console"
        :class="{ collapsed: stageConsoleCollapsed }"
        :style="stageConsoleStyle"
      >
        <div class="stage-console-head">
          <div class="stage-console-left">
            <div class="tabs stage-console-tabs">
              <button
                class="tab icon-btn"
                type="button"
                :class="{ active: stageConsoleTab === 'control' }"
                :aria-label="t('app.tabs.control')"
                :title="t('app.tabs.control')"
                @click="stageConsoleTab = 'control'"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <line x1="12" y1="3" x2="12" y2="7" />
                  <line x1="12" y1="17" x2="12" y2="21" />
                  <line x1="3" y1="12" x2="7" y2="12" />
                  <line x1="17" y1="12" x2="21" y2="12" />
                </svg>
              </button>
              <button
                class="tab icon-btn"
                type="button"
                :class="{ active: stageConsoleTab === 'session' }"
                :aria-label="t('app.tabs.session')"
                :title="t('app.tabs.session')"
                @click="stageConsoleTab = 'session'"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 4h7l4 4v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
                  <path d="M14 4v4h4" />
                </svg>
              </button>
              <button
                class="tab icon-btn"
                type="button"
                :class="{ active: stageConsoleTab === 'log' }"
                :aria-label="t('app.tabs.log')"
                :title="t('app.tabs.log')"
                @click="stageConsoleTab = 'log'"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 7l4 4-4 4" />
                  <line x1="11" y1="17" x2="19" y2="17" />
                </svg>
              </button>
            </div>
          </div>
          <div class="stage-console-right">
            <div v-if="stageConsoleTab === 'log'" class="stage-console-log-actions">
              <span
                v-if="logStatus"
                class="panel-status"
                :class="logStatusClass"
              >
                {{ logStatusLabel }}
              </span>
              <button
                class="ghost icon-btn"
                type="button"
                :aria-label="logLive ? t('log.action.pause') : t('log.action.live')"
                :title="logLive ? t('log.action.pause') : t('log.action.live')"
                @click="toggleRunLog"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <g v-if="logLive">
                    <rect class="icon-fill" x="6" y="5" width="4" height="14" rx="1" />
                    <rect class="icon-fill" x="14" y="5" width="4" height="14" rx="1" />
                  </g>
                  <polygon
                    v-else
                    class="icon-fill"
                    points="8,5 19,12 8,19"
                  />
                </svg>
              </button>
              <button
                class="ghost icon-btn"
                type="button"
                :aria-label="t('log.action.copy')"
                :title="t('log.action.copy')"
                @click="copyRunLog"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="9" y="9" width="10" height="12" rx="2" />
                  <path d="M7 15H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
            <button
              class="ghost icon-btn"
              type="button"
              :aria-expanded="!stageConsoleCollapsed"
              :aria-label="t('app.toggleConsole')"
              :title="t('app.toggleConsole')"
              @click="toggleStageConsole"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  v-if="stageConsoleCollapsed"
                  d="M6 15l6-6 6 6"
                />
                <path
                  v-else
                  d="M6 9l6 6 6-6"
                />
              </svg>
            </button>
          </div>
        </div>
        <div v-show="!stageConsoleCollapsed" class="stage-console-body">
          <div v-show="stageConsoleTab === 'control'" class="stage-console-pane">
            <DeviceControls
              v-model:deviceId="controlDeviceId"
              :devices="devices"
              :statusMessage="controlStatusMessage"
              :streamActive="controlStreamActive"
              :streamMode="controlStreamMode"
              :streamSession="controlStreamSession"
              :mjpegAvailable="mjpegAvailable"
              :inputEnabled="controlInputEnabled"
              @command="handleDeviceCommand"
              @stream-toggle="toggleLiveStream"
              @stream-mjpeg="useMjpegStream"
              @stream-webrtc="retryWebRTCStream"
              @stream-session-start="handleStreamSessionStart"
              @stream-session-stop="handleStreamSessionStop"
              @stream-session-restart="handleStreamSessionRestart"
              @stream-session-config="handleStreamSessionConfig"
            />
          </div>
          <div v-show="stageConsoleTab === 'session'" class="stage-console-pane">
            <div class="stage-session">
              <div v-if="!sessionDetails || !sessionDisplay" class="session-empty">
                {{ t("app.sessionDetailsEmpty") }}
              </div>
              <div v-else class="session-grid">
                <section class="session-card">
                  <div class="session-card-head">
                    <div class="session-card-title">
                      {{ t("sessionDetails.device") }}
                    </div>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.deviceId") }}
                    </span>
                    <span
                      class="session-value mono"
                      :class="{ 'is-empty': sessionDisplay.deviceId.empty }"
                    >
                      {{ sessionDisplay.deviceId.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.sessionStatus") }}
                    </span>
                    <span
                      class="status-badge"
                      :class="sessionStatusClass(sessionDetails.session?.status)"
                    >
                      {{ sessionStatusLabel(sessionDetails.session?.status) }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.pending") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.pending.empty }"
                    >
                      {{ sessionDisplay.pending.text }}
                    </span>
                  </div>
                  <div class="session-row session-row-stack">
                    <span class="session-label">
                      {{ t("sessionDetails.currentCommand") }}
                    </span>
                    <span
                      class="session-value mono wrap"
                      :class="{ 'is-empty': sessionDisplay.currentCommand.empty }"
                    >
                      {{ sessionDisplay.currentCommand.text }}
                    </span>
                  </div>
                </section>
                <section class="session-card">
                  <div class="session-card-head">
                    <div class="session-card-title">
                      {{ t("sessionDetails.session") }}
                    </div>
                  </div>
                  <div class="session-row session-row-stack">
                    <span class="session-label">
                      {{ t("sessionDetails.lastError") }}
                    </span>
                    <span
                      class="session-value wrap"
                      :class="{ 'is-empty': sessionDisplay.lastError.empty }"
                    >
                      {{ sessionDisplay.lastError.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.createdAt") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.createdAt.empty }"
                    >
                      {{ sessionDisplay.createdAt.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.updatedAt") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.updatedAt.empty }"
                    >
                      {{ sessionDisplay.updatedAt.text }}
                    </span>
                  </div>
                </section>
                <section class="session-card">
                  <div class="session-card-head">
                    <div class="session-card-title">
                      {{ t("sessionDetails.stream") }}
                    </div>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.mode") }}
                    </span>
                    <span
                      class="status-badge"
                      :class="streamModeClass(sessionDetails.connection?.mode)"
                    >
                      {{ streamModeLabel(sessionDetails.connection?.mode) }}
                    </span>
                  </div>
                  <div class="session-row session-row-stack">
                    <span class="session-label">
                      {{ t("sessionDetails.streamStatus") }}
                    </span>
                    <span
                      class="session-value wrap"
                      :class="{ 'is-empty': sessionDisplay.streamStatus.empty }"
                    >
                      {{ sessionDisplay.streamStatus.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.resolution") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.resolution.empty }"
                    >
                      {{ sessionDisplay.resolution.text }}
                    </span>
                  </div>
                </section>
                <section class="session-card">
                  <div class="session-card-head">
                    <div class="session-card-title">
                      {{ t("sessionDetails.stats") }}
                    </div>
                    <div
                      v-if="sessionDisplay.age"
                      class="session-pill"
                    >
                      {{ sessionDisplay.age }}
                    </div>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.fps") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.fps.empty }"
                    >
                      {{ sessionDisplay.fps.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.bitrate") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.bitrate.empty }"
                    >
                      {{ sessionDisplay.bitrate.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.packets") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.packets.empty }"
                    >
                      {{ sessionDisplay.packets.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.frames") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.frames.empty }"
                    >
                      {{ sessionDisplay.frames.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.jitter") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.jitter.empty }"
                    >
                      {{ sessionDisplay.jitter.text }}
                    </span>
                  </div>
                  <div class="session-row">
                    <span class="session-label">
                      {{ t("sessionDetails.lastUpdate") }}
                    </span>
                    <span
                      class="session-value"
                      :class="{ 'is-empty': sessionDisplay.lastUpdate.empty }"
                    >
                      {{ sessionDisplay.lastUpdate.text }}
                    </span>
                  </div>
                </section>
              </div>
            </div>
          </div>
          <div
            v-show="stageConsoleTab === 'log'"
            class="stage-console-pane stage-log-pane"
          >
            <div v-if="runLogMeta" class="panel-meta">{{ runLogMeta }}</div>
            <div class="log-body stage-log-body">
              <pre class="log-lines">{{ runLogText }}</pre>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import RunConsole from "./components/RunConsole.vue";
import RunTimeline from "./components/RunTimeline.vue";
import StudioBrand from "./components/StudioBrand.vue";
import LiveDevices from "./components/LiveDevices.vue";
import DeviceControls from "./components/DeviceControls.vue";

import { setLocale, type Locale } from "./i18n";
import { useAppStore } from "./store/app";
import { useDevicesStore } from "./store/devices";
import { useRunsStore } from "./store/runs";
import { useStreamsStore } from "./store/streams";
import type {
  DeviceCommandRequest,
  RunRequest,
  StepDetails,
  StreamSessionConfigRequest,
} from "./api/types";

const app = useAppStore();
const runsStore = useRunsStore();
const devicesStore = useDevicesStore();
const streamsStore = useStreamsStore();
const { t, locale } = useI18n();

const {
  runs,
  steps,
  selectedRunId,
  selectedStepId,
  currentRun,
  currentStep,
  runLog,
  runLogMessage,
  logLive,
  logStatus,
} = storeToRefs(runsStore);
const { devices, deviceSessions } = storeToRefs(devicesStore);
const {
  liveConnections,
  liveMessages,
  liveStats,
  streamSessions,
  mjpegAvailable,
  webrtcConfig,
} = storeToRefs(streamsStore);

const form = reactive({
  goal: "",
  maxSteps: 5,
  planSteps: 5,
  planVerify: "llm",
  device: "",
  execute: true,
  plan: true,
  skills: false,
  textOnly: false,
  planResume: true,
});

const runSubmitting = ref(false);
const controlDeviceId = ref("");
const stageConsoleCollapsed = ref(false);
const stageConsoleTab = ref<"control" | "session" | "log">("control");
const railWidth = ref(320);
const resizing = ref(false);
const railCollapsed = ref(false);
const stageConsoleHeight = ref(320);
const stageConsoleResizing = ref(false);
const nextLocale = computed<Locale>(() =>
  (locale.value === "en" ? "zh" : "en") as Locale,
);
const languageToggleLabel = computed(() =>
  t("app.switchLanguage", { lang: t(`language.${nextLocale.value}`) }),
);
const resizeState = reactive({
  startX: 0,
  startWidth: 320,
});
const stageResizeState = reactive({
  startY: 0,
  startHeight: 320,
});
const lastRailWidth = ref(320);
const minRailWidth = 260;
const maxRailWidth = 520;
const collapsedRailWidth = 84;
const minStageConsoleHeight = 220;

function normalizeStatus(value?: string) {
  const status = (value || "idle").toString().toLowerCase();
  if (["running", "finished", "failed", "stopping", "stopped"].includes(status)) {
    return status;
  }
  return "idle";
}

function formatJson(value: unknown) {
  if (value === null || value === undefined) {
    return t("common.noData");
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return t("common.invalidJson");
  }
}

type DisplayValue = {
  text: string;
  empty: boolean;
};

const EMPTY_VALUE = "—";

function displayText(value?: string | null): DisplayValue {
  if (!value) {
    return { text: EMPTY_VALUE, empty: true };
  }
  return { text: value, empty: false };
}

function displayNumber(
  value?: number | null,
  digits = 0,
  unit?: string,
  scale = 1,
): DisplayValue {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { text: EMPTY_VALUE, empty: true };
  }
  const scaled = value * scale;
  const base = digits > 0 ? scaled.toFixed(digits) : `${Math.round(scaled)}`;
  return { text: unit ? `${base} ${unit}` : base, empty: false };
}

function displayBitrate(value?: number | null): DisplayValue {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { text: EMPTY_VALUE, empty: true };
  }
  if (value >= 1000) {
    return displayNumber(value / 1000, 1, "Mbps");
  }
  return displayNumber(value, 0, "kbps");
}

function displayJitter(value?: number | null): DisplayValue {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { text: EMPTY_VALUE, empty: true };
  }
  const jitterMs = value * 1000;
  const digits = jitterMs < 10 ? 2 : jitterMs < 100 ? 1 : 0;
  return displayNumber(jitterMs, digits, "ms");
}

function displayTimestamp(value?: number | null): DisplayValue {
  if (value === null || value === undefined) {
    return { text: EMPTY_VALUE, empty: true };
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return { text: EMPTY_VALUE, empty: true };
  }
  return { text: date.toLocaleString(), empty: false };
}

function displayResolution(
  stats?: { width?: number | null; height?: number | null } | null,
): DisplayValue {
  const width = stats?.width ?? null;
  const height = stats?.height ?? null;
  if (!width || !height) {
    return { text: EMPTY_VALUE, empty: true };
  }
  return { text: `${width} x ${height}`, empty: false };
}

function displayAge(value?: number | null): string {
  if (!value) {
    return "";
  }
  const diffMs = Math.max(0, Date.now() - value);
  if (diffMs < 1000) {
    return t("sessionDetails.updatedNow");
  }
  if (diffMs < 60000) {
    return t("sessionDetails.updatedSeconds", {
      seconds: Math.max(1, Math.round(diffMs / 1000)),
    });
  }
  if (diffMs < 3600000) {
    return t("sessionDetails.updatedMinutes", {
      minutes: Math.max(1, Math.round(diffMs / 60000)),
    });
  }
  return t("sessionDetails.updatedHours", {
    hours: Math.max(1, Math.round(diffMs / 3600000)),
  });
}

function resolveStatusLabel(status: string) {
  const key = `status.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function sessionStatusLabel(status?: string | null) {
  if (!status) {
    return t("status.none");
  }
  return resolveStatusLabel(status.toLowerCase());
}

function sessionStatusClass(status?: string | null) {
  if (!status) {
    return "unknown";
  }
  const normalized = status.toLowerCase();
  const known = new Set([
    "running",
    "finished",
    "failed",
    "stopping",
    "stopped",
    "done",
    "pending",
    "idle",
    "offline",
    "unauthorized",
  ]);
  return known.has(normalized) ? normalized : "unknown";
}

function streamModeLabel(mode?: string | null) {
  if (!mode) {
    return t("stream.off");
  }
  const key = `stream.${mode}`;
  const label = t(key);
  return label === key ? mode : label;
}

function streamModeClass(mode?: string | null) {
  if (!mode) {
    return "offline";
  }
  if (mode === "webrtc" || mode === "mjpeg") {
    return mode;
  }
  return "unknown";
}

function toPositiveInt(value: number | string, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (Number.isFinite(parsed) && parsed > 0) {
    return parsed;
  }
  return fallback;
}

function clampRailWidth(value: number) {
  return Math.min(maxRailWidth, Math.max(minRailWidth, value));
}

function maxStageConsoleHeight() {
  return Math.max(minStageConsoleHeight, Math.floor(window.innerHeight * 0.6));
}

function clampStageConsoleHeight(value: number) {
  return Math.min(maxStageConsoleHeight(), Math.max(minStageConsoleHeight, value));
}

function startResize(event: PointerEvent) {
  if (railCollapsed.value) {
    return;
  }
  if (event.button !== 0) {
    return;
  }
  resizing.value = true;
  resizeState.startX = event.clientX;
  resizeState.startWidth = railWidth.value;
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
  window.addEventListener("pointermove", handleResizeMove);
  window.addEventListener("pointerup", stopResize);
  window.addEventListener("pointercancel", stopResize);
  event.preventDefault();
}

function startStageResize(event: PointerEvent) {
  if (stageConsoleCollapsed.value) {
    return;
  }
  if (event.button !== 0) {
    return;
  }
  stageConsoleResizing.value = true;
  stageResizeState.startY = event.clientY;
  stageResizeState.startHeight = stageConsoleHeight.value;
  document.body.style.cursor = "row-resize";
  document.body.style.userSelect = "none";
  window.addEventListener("pointermove", handleStageResizeMove);
  window.addEventListener("pointerup", stopStageResize);
  window.addEventListener("pointercancel", stopStageResize);
  event.preventDefault();
}

function handleResizeMove(event: PointerEvent) {
  if (!resizing.value) {
    return;
  }
  const delta = event.clientX - resizeState.startX;
  railWidth.value = clampRailWidth(resizeState.startWidth + delta);
}

function handleStageResizeMove(event: PointerEvent) {
  if (!stageConsoleResizing.value) {
    return;
  }
  const delta = stageResizeState.startY - event.clientY;
  stageConsoleHeight.value = clampStageConsoleHeight(
    stageResizeState.startHeight + delta,
  );
}

function stopResize() {
  if (!resizing.value) {
    return;
  }
  resizing.value = false;
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  window.removeEventListener("pointermove", handleResizeMove);
  window.removeEventListener("pointerup", stopResize);
  window.removeEventListener("pointercancel", stopResize);
  window.localStorage.setItem("mrpa.railWidth", String(railWidth.value));
}

function stopStageResize() {
  if (!stageConsoleResizing.value) {
    return;
  }
  stageConsoleResizing.value = false;
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  window.removeEventListener("pointermove", handleStageResizeMove);
  window.removeEventListener("pointerup", stopStageResize);
  window.removeEventListener("pointercancel", stopStageResize);
  window.localStorage.setItem(
    "mrpa.stageConsoleHeight",
    String(stageConsoleHeight.value),
  );
}

function toggleRail() {
  if (railCollapsed.value) {
    railCollapsed.value = false;
    railWidth.value = clampRailWidth(lastRailWidth.value);
    return;
  }
  lastRailWidth.value = railWidth.value;
  railCollapsed.value = true;
  railWidth.value = collapsedRailWidth;
}

function toggleLanguage() {
  setLocale(nextLocale.value);
}

function buildVerificationPayload(step?: StepDetails | null) {
  const decision = step?.decision || {};
  const payload: Record<string, unknown> = {};
  if (step?.verification) {
    payload.verification = step.verification;
  }
  if (decision.plan_verify) {
    payload.plan_verify = decision.plan_verify;
  }
  return Object.keys(payload).length ? payload : null;
}

function getDeviceSessionStatus(deviceId: string) {
  if (!deviceId) {
    return t("session.selectDevice");
  }
  if (isClientOffline(deviceId)) {
    return t("session.offline");
  }
  const session = deviceSessions.value.find(
    (item) => item.device_id === deviceId,
  );
  if (!session) {
    return t("session.none");
  }
  if (session.last_error) {
    return t("session.error", { message: session.last_error });
  }
  if (session.status === "running") {
    return t("session.runningQueue", { pending: session.pending });
  }
  if (session.pending > 0) {
    return t("session.queuedPending", { pending: session.pending });
  }
  return t("session.idle");
}

function isClientOffline(deviceId: string) {
  const device = devices.value.find((item) => item.id === deviceId);
  const status = (device?.client_status || "unknown").toString().toLowerCase();
  return status === "offline";
}

async function handleRunSubmit() {
  const goal = form.goal.trim();
  if (!goal) {
    return;
  }
  const payload: RunRequest = {
    goal,
    execute: form.execute,
    plan: form.plan,
    plan_max_steps: toPositiveInt(form.planSteps, 5),
    plan_verify: form.planVerify,
    plan_resume: form.planResume,
    max_steps: toPositiveInt(form.maxSteps, 5),
    skills: form.skills,
    text_only: form.textOnly,
  };
  if (form.device) {
    payload.device = form.device;
  }

  runSubmitting.value = true;
  try {
    await runsStore.startRun(payload);
  } catch (error) {
    app.setError(error);
  } finally {
    runSubmitting.value = false;
  }
}

async function handleStopRun() {
  if (!selectedRunId.value) {
    return;
  }
  try {
    await runsStore.stopRun(selectedRunId.value);
  } catch (error) {
    app.setError(error);
  }
}

function toggleRunLog() {
  runsStore.toggleLogStream();
}

function toggleStageConsole() {
  stageConsoleCollapsed.value = !stageConsoleCollapsed.value;
}

async function copyRunLog() {
  if (!runLogText.value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(runLogText.value);
  } catch (_error) {
    // ignore clipboard errors
  }
}

async function refreshAll(options: { keepStep?: boolean; selectNewest?: boolean }) {
  try {
    await runsStore.refreshAll(options);
  } catch (error) {
    app.setError(error);
  }
}

async function refreshDevices() {
  try {
    await devicesStore.refreshDevices();
    streamsStore.syncDevices(devices.value);
    if (controlDeviceId.value) {
      void streamsStore.refreshStreamSession(controlDeviceId.value);
    }
  } catch (error) {
    app.setError(error);
  }
}

async function selectRun(runId: string) {
  try {
    await runsStore.selectRun(runId);
  } catch (error) {
    app.setError(error);
  }
}

async function selectStep(stepId: string) {
  try {
    await runsStore.selectStep(stepId);
  } catch (error) {
    app.setError(error);
  }
}

async function toggleLiveStream(deviceId: string) {
  try {
    await streamsStore.toggleLiveStream(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

function handleLiveSelect(deviceId: string) {
  if (!deviceId) {
    return;
  }
  controlDeviceId.value = deviceId;
}

async function useMjpegStream(deviceId: string) {
  try {
    streamsStore.useMjpegStream(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

async function retryWebRTCStream(deviceId: string) {
  try {
    await streamsStore.retryWebRTCStream(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

async function handleDeviceCommand(
  deviceId: string,
  payload: DeviceCommandRequest,
) {
  try {
    if (payload.type.startsWith("touch_")) {
      void devicesStore.sendDeviceCommand(deviceId, payload);
      return;
    }
    await devicesStore.sendDeviceCommand(deviceId, payload);
    if (!payload.type.startsWith("touch_")) {
      await devicesStore.refreshDeviceCommands(deviceId, 10);
    }
  } catch (error) {
    app.setError(error);
  }
}

async function handleStreamSessionStart(deviceId: string) {
  try {
    await streamsStore.startStreamSession(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

async function handleStreamSessionStop(deviceId: string) {
  try {
    await streamsStore.stopStreamSession(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

async function handleStreamSessionRestart(deviceId: string) {
  try {
    await streamsStore.restartStreamSession(deviceId);
  } catch (error) {
    app.setError(error);
  }
}

async function handleStreamSessionConfig(
  deviceId: string,
  config: StreamSessionConfigRequest,
) {
  try {
    await streamsStore.updateStreamSessionConfig(deviceId, config);
  } catch (error) {
    app.setError(error);
  }
}


const runStatus = computed(() => normalizeStatus(currentRun.value?.status || "idle"));
const controlStatusMessage = computed(() =>
  getDeviceSessionStatus(controlDeviceId.value),
);
const controlSession = computed(
  () =>
    deviceSessions.value.find(
      (session) => session.device_id === controlDeviceId.value,
    ) || null,
);
const controlStreamConnection = computed(() => {
  if (!controlDeviceId.value) {
    return null;
  }
  return liveConnections.value[controlDeviceId.value] || null;
});
const controlStreamActive = computed(() => {
  if (controlDeviceId.value && isClientOffline(controlDeviceId.value)) {
    return false;
  }
  return Boolean(controlStreamConnection.value);
});
const controlStreamMode = computed(() => {
  if (controlDeviceId.value && isClientOffline(controlDeviceId.value)) {
    return null;
  }
  return controlStreamConnection.value ? controlStreamConnection.value.mode : null;
});
const controlStreamSession = computed(() => {
  if (!controlDeviceId.value) {
    return null;
  }
  return streamSessions.value[controlDeviceId.value] || null;
});
const inputDriver = computed(() =>
  (webrtcConfig.value?.input_driver || "").toLowerCase(),
);
const inputAllowFallback = computed(() => {
  if (typeof webrtcConfig.value?.input_allow_fallback === "boolean") {
    return webrtcConfig.value.input_allow_fallback;
  }
  return true;
});
const requiresScrcpyControl = computed(
  () => inputDriver.value === "scrcpy" && !inputAllowFallback.value,
);

function scrcpyControlReady(deviceId: string) {
  const session = streamSessions.value[deviceId];
  if (!session) {
    return false;
  }
  const status = (session.status || "stopped").toLowerCase();
  return status === "running" && Boolean(session.config?.control);
}

const inputAvailableByDevice = computed<Record<string, boolean>>(() => {
  if (!requiresScrcpyControl.value) {
    return {};
  }
  const availability: Record<string, boolean> = {};
  devices.value.forEach((device) => {
    if (isClientOffline(device.id)) {
      availability[device.id] = false;
      return;
    }
    availability[device.id] = scrcpyControlReady(device.id);
  });
  return availability;
});

const controlInputEnabled = computed(() => {
  if (!requiresScrcpyControl.value) {
    return true;
  }
  if (!controlDeviceId.value) {
    return false;
  }
  if (isClientOffline(controlDeviceId.value)) {
    return false;
  }
  return scrcpyControlReady(controlDeviceId.value);
});

const decisionText = computed(() => formatJson(currentStep.value?.decision));
const promptText = computed(() => currentStep.value?.prompt || t("common.noData"));
const responseText = computed(() => currentStep.value?.response || t("common.noData"));
const contextText = computed(() => formatJson(currentStep.value?.context));
const verificationText = computed(() =>
  formatJson(buildVerificationPayload(currentStep.value)),
);
const stageConsoleStyle = computed(() => {
  if (stageConsoleCollapsed.value) {
    return {};
  }
  return { height: `${stageConsoleHeight.value}px` };
});
const sessionDetails = computed(() => {
  if (!controlDeviceId.value) {
    return null;
  }
  const deviceId = controlDeviceId.value;
  const connection = liveConnections.value[deviceId] || null;
  const stats = liveStats.value[deviceId] || null;
  return {
    deviceId,
    session: controlSession.value,
    connection,
    stats,
  };
});
const sessionDisplay = computed(() => {
  if (!sessionDetails.value) {
    return null;
  }
  const { deviceId, session, connection, stats } = sessionDetails.value;
  return {
    deviceId: displayText(deviceId),
    pending: displayNumber(session?.pending ?? null, 0),
    currentCommand: displayText(session?.current_command_id ?? null),
    lastError: displayText(session?.last_error ?? null),
    createdAt: displayTimestamp(session?.created_at ?? null),
    updatedAt: displayTimestamp(session?.updated_at ?? null),
    streamStatus: displayText(connection?.status ?? null),
    resolution: displayResolution(stats ?? null),
    fps: displayNumber(stats?.fps ?? null, 1),
    bitrate: displayBitrate(stats?.bitrateKbps ?? null),
    packets: displayNumber(stats?.packets ?? null, 0),
    frames: displayNumber(stats?.frames ?? null, 0),
    jitter: displayJitter(stats?.jitter ?? null),
    lastUpdate: displayTimestamp(stats?.updatedAt ?? null),
    age: displayAge(stats?.updatedAt ?? null),
  };
});
const runLogText = computed(() => {
  if (runLog.value?.text) {
    return runLog.value.text;
  }
  if (runLogMessage.value) {
    const message = runLogMessage.value;
    if (message === "No log loaded.") {
      return t("log.noLog");
    }
    if (message === "No run selected.") {
      return t("log.noRun");
    }
    if (message === "Log unavailable.") {
      return t("log.unavailable");
    }
    return message;
  }
  return t("log.noLog");
});
const runLogMeta = computed(() => {
  if (!runLog.value) {
    return "";
  }
  if (runLog.value.truncated) {
    return t("log.meta.showing", {
      lines: runLog.value.lines,
      total: runLog.value.total_lines,
    });
  }
  return t("log.meta.lines", { lines: runLog.value.lines });
});

function formatLogStatus(value?: string) {
  if (!value) {
    return "";
  }
  const status = value.toLowerCase();
  const reconnectMatch = status.match(/reconnecting in (\d+)s/);
  if (reconnectMatch) {
    return t("log.status.reconnectingIn", { seconds: reconnectMatch[1] });
  }
  if (status.includes("reconnect")) {
    return t("log.status.reconnecting");
  }
  if (status === "connecting") {
    return t("log.status.connecting");
  }
  if (status === "idle") {
    return t("status.idle");
  }
  if (status === "error") {
    return t("log.status.error");
  }
  if (status === "live") {
    return t("log.status.live");
  }
  if (status === "paused") {
    return t("log.status.paused");
  }
  return value;
}

const logStatusLabel = computed(() => formatLogStatus(logStatus.value));
const logStatusClass = computed(() => {
  const status = (logStatus.value || "").toLowerCase();
  if (status.includes("reconnect") || status === "connecting") {
    return "warn";
  }
  if (status === "error") {
    return "error";
  }
  if (status === "live") {
    return "ok";
  }
  if (status === "paused") {
    return "muted";
  }
  return "muted";
});

onMounted(() => {
  (window as unknown as { __webrtcConnections?: unknown }).__webrtcConnections =
    streamsStore.liveConnections;
  setLocale(locale.value as Locale);
  streamsStore.ensureWebRTCConfig().catch(() => {});
  const storedWidth = window.localStorage.getItem("mrpa.railWidth");
  if (storedWidth) {
    const parsed = Number.parseInt(storedWidth, 10);
    if (Number.isFinite(parsed)) {
      railWidth.value = clampRailWidth(parsed);
      lastRailWidth.value = railWidth.value;
    }
  }
  const storedHeight = window.localStorage.getItem("mrpa.stageConsoleHeight");
  if (storedHeight) {
    const parsed = Number.parseInt(storedHeight, 10);
    if (Number.isFinite(parsed)) {
      stageConsoleHeight.value = clampStageConsoleHeight(parsed);
    }
  }
  refreshAll({ selectNewest: true });
  refreshDevices();
  devicesStore.refreshDeviceSessions().catch(() => {});
});

onBeforeUnmount(() => {
  runsStore.cleanup();
  streamsStore.cleanup();
  stopResize();
  stopStageResize();
});
watch(
  devices,
  (next) => {
    if (!controlDeviceId.value && next.length) {
      controlDeviceId.value = next[0].id;
    }
  },
  { immediate: true },
);

watch(
  controlDeviceId,
  (next) => {
    if (next) {
      void streamsStore.refreshStreamSession(next);
    }
  },
  { immediate: true },
);
</script>
