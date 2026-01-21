<template>
  <aside class="inspector">
    <section class="panel">
      <div class="panel-header">
        <h2>{{ t("inspector.runDetails") }}</h2>
        <button
          class="ghost"
          type="button"
          :disabled="!props.canStop"
          @click="emit('stop')"
        >
          {{ t("form.stop") }}
        </button>
      </div>
      <pre>{{ props.runDetailsText }}</pre>
    </section>
    <section class="panel">
      <div class="panel-header">
        <h2>{{ t("inspector.verification") }}</h2>
      </div>
      <pre>{{ props.verificationText }}</pre>
    </section>
    <section class="panel">
      <div class="panel-header">
        <h2>{{ t("inspector.runLog") }}</h2>
        <div class="panel-actions">
          <span
            class="panel-status"
            :class="statusClass"
            v-if="props.runLogStatus"
          >
            {{ logStatusLabel }}
          </span>
          <button class="ghost" type="button" @click="emit('toggle-log')">
            {{ props.runLogLive ? t("inspector.pause") : t("inspector.live") }}
          </button>
          <button class="ghost" type="button" @click="emit('refresh-log')">
            {{ t("inspector.refresh") }}
          </button>
        </div>
      </div>
      <div v-if="props.runLogMeta" class="panel-meta">
        {{ props.runLogMeta }}
      </div>
      <div class="log-tools">
        <div class="log-filters">
          <button
            class="chip"
            :class="{ active: levelFilter === 'all' }"
            type="button"
            @click="setLevelFilter('all')"
          >
            {{ t("inspector.all") }}
          </button>
          <button
            class="chip"
            :class="{ active: levelFilter === 'error' }"
            type="button"
            @click="setLevelFilter('error')"
          >
            {{ t("inspector.error") }}
          </button>
          <button
            class="chip"
            :class="{ active: levelFilter === 'warn' }"
            type="button"
            @click="setLevelFilter('warn')"
          >
            {{ t("inspector.warn") }}
          </button>
          <button
            class="chip"
            :class="{ active: levelFilter === 'info' }"
            type="button"
            @click="setLevelFilter('info')"
          >
            {{ t("inspector.info") }}
          </button>
        </div>
        <input
          v-model="logSearch"
          class="log-filter"
          type="text"
          :placeholder="t('inspector.searchLogs')"
          @keydown.enter.prevent="findNextMatch"
        />
        <button
          class="chip"
          type="button"
          :disabled="!hasMatches"
          @click="findPrevMatch"
        >
          {{ t("inspector.prev") }}
        </button>
        <button
          class="chip"
          type="button"
          :disabled="!hasMatches"
          @click="findNextMatch"
        >
          {{ t("inspector.next") }}
        </button>
        <button class="ghost" type="button" @click="copyLog">
          {{ t("inspector.copy") }}
        </button>
        <button class="ghost" type="button" @click="downloadLog">
          {{ t("inspector.download") }}
        </button>
        <label class="log-follow">
          <input v-model="followLog" type="checkbox" />
          {{ t("inspector.follow") }}
        </label>
      </div>
      <div class="log-body" ref="logBody">
        <div class="log-lines">
          <div
            v-for="(line, index) in visibleLines"
            :key="index"
            class="log-line"
            :class="[
              line.severity,
              { active: index === activeLineIndex },
            ]"
            v-html="line.html"
            :ref="(el) => setLineRef(index, el)"
          ></div>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch, type ComponentPublicInstance } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  runDetailsText: string;
  verificationText: string;
  runLogText: string;
  runLogMeta: string;
  runId: string;
  runLogLive: boolean;
  runLogStatus: string;
  canStop: boolean;
}>();

const emit = defineEmits<{
  (e: "stop"): void;
  (e: "refresh-log"): void;
  (e: "toggle-log"): void;
}>();

const { t } = useI18n();

const logSearch = ref("");
const levelFilter = ref<"all" | "error" | "warn" | "info">("all");
const followLog = ref(true);
const logBody = ref<HTMLElement | null>(null);
const activeMatch = ref(0);
const lineRefs = new Map<number, HTMLElement>();

const rawLines = computed(() => {
  if (!props.runLogText) {
    return [];
  }
  const lines = props.runLogText.replace(/\r/g, "").split("\n");
  if (lines.length && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
});

const statusClass = computed(() => {
  const status = (props.runLogStatus || "").toLowerCase();
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

const logStatusLabel = computed(() => {
  const status = (props.runLogStatus || "").toLowerCase();
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
  return props.runLogStatus;
});

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function detectSeverity(line: string) {
  if (/\b(error|failed|exception|traceback)\b/i.test(line)) {
    return "error";
  }
  if (/\bwarn(ing)?\b/i.test(line)) {
    return "warn";
  }
  if (/\binfo\b/i.test(line)) {
    return "info";
  }
  return "normal";
}

const searchNeedle = computed(() => logSearch.value.trim().toLowerCase());

const visibleLines = computed(() => {
  const needle = searchNeedle.value;
  const severityFilter = levelFilter.value;
  const regex = needle ? new RegExp(escapeRegex(needle), "ig") : null;
  return rawLines.value
    .map((line) => {
      const severity = detectSeverity(line);
      if (severityFilter !== "all" && severity !== severityFilter) {
        return null;
      }
      if (needle && !line.toLowerCase().includes(needle)) {
        return null;
      }
      const escaped = escapeHtml(line);
      const html = regex
        ? escaped.replace(regex, (match) => `<span class="log-match">${match}</span>`)
        : escaped;
      return {
        text: line,
        severity,
        html,
        match: Boolean(regex && line.toLowerCase().includes(needle)),
      };
    })
    .filter((item) => item !== null) as Array<{
    text: string;
    severity: string;
    html: string;
    match: boolean;
  }>;
});

const matchIndices = computed(() => {
  if (!searchNeedle.value) {
    return [];
  }
  return visibleLines.value
    .map((line, index) => (line.match ? index : -1))
    .filter((index) => index >= 0);
});

const hasMatches = computed(() => matchIndices.value.length > 0);
const activeLineIndex = computed(() => {
  if (!matchIndices.value.length) {
    return -1;
  }
  const index = matchIndices.value[activeMatch.value % matchIndices.value.length];
  return index ?? -1;
});

function scrollToBottom() {
  if (!logBody.value) {
    return;
  }
  logBody.value.scrollTop = logBody.value.scrollHeight;
}

function scrollToLine(index: number) {
  const el = lineRefs.get(index);
  if (!el) {
    return;
  }
  el.scrollIntoView({ block: "center" });
}

function setLineRef(index: number, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) {
    lineRefs.set(index, el);
    return;
  }
  lineRefs.delete(index);
}

function setLevelFilter(filter: "all" | "error" | "warn" | "info") {
  levelFilter.value = filter;
  activeMatch.value = 0;
}

function findNextMatch() {
  if (!matchIndices.value.length) {
    return;
  }
  activeMatch.value = (activeMatch.value + 1) % matchIndices.value.length;
  scrollToLine(matchIndices.value[activeMatch.value]);
}

function findPrevMatch() {
  if (!matchIndices.value.length) {
    return;
  }
  const next =
    (activeMatch.value - 1 + matchIndices.value.length) %
    matchIndices.value.length;
  activeMatch.value = next;
  scrollToLine(matchIndices.value[activeMatch.value]);
}

async function copyLog() {
  const text = visibleLines.value.map((line) => line.text).join("\n");
  if (!text) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    // ignore clipboard errors
  }
}

function downloadLog() {
  const text = visibleLines.value.map((line) => line.text).join("\n");
  if (!text) {
    return;
  }
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = props.runId ? `${props.runId}.log` : "run.log";
  link.click();
  URL.revokeObjectURL(url);
}

watch(
  () => visibleLines.value.length,
  () => {
    if (!followLog.value) {
      return;
    }
    nextTick(() => scrollToBottom());
  },
);

watch(
  () => followLog.value,
  (next) => {
    if (next) {
      nextTick(() => scrollToBottom());
    }
  },
);

watch(
  () => [logSearch.value, levelFilter.value],
  () => {
    activeMatch.value = 0;
    if (matchIndices.value.length) {
      nextTick(() => scrollToLine(matchIndices.value[0]));
    }
  },
);
</script>
