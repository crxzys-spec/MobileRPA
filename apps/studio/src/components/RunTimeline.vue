<template>
  <section class="panel timeline">
    <div class="timeline-head">
      <div class="panel-header">
        <div>
          <h2>{{ t("timeline.title") }}</h2>
          <div v-if="props.currentRun" class="panel-meta">
            {{ runMetaLabel(props.currentRun) }}
          </div>
        </div>
        <div class="panel-actions">
          <button
            class="ghost icon-btn timeline-switch-btn"
            type="button"
            :aria-expanded="showSwitcher"
            :aria-label="showSwitcher ? t('timeline.hideRuns') : t('timeline.showRuns')"
            :title="showSwitcher ? t('timeline.hideRuns') : t('timeline.showRuns')"
            aria-controls="timeline-switcher"
            @click="showSwitcher = !showSwitcher"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <line x1="5" y1="7" x2="19" y2="7" />
              <line x1="5" y1="12" x2="19" y2="12" />
              <line x1="5" y1="17" x2="19" y2="17" />
            </svg>
          </button>
        </div>
      </div>
      <div
        v-show="showSwitcher"
        id="timeline-switcher"
        class="timeline-switcher"
      >
        <input
          v-model.trim="search"
          class="timeline-search"
          type="text"
          :placeholder="t('timeline.searchRuns')"
        />
        <select
          v-model="activeRunId"
          class="timeline-select"
          @change="handleRunChange"
        >
          <option value="" disabled>{{ t("timeline.selectRun") }}</option>
          <option
            v-for="run in filteredRuns"
            :key="run.id"
            :value="run.id"
          >
            {{ runOptionLabel(run) }}
          </option>
        </select>
      </div>
    </div>
    <div class="timeline-body">
      <div v-if="!props.currentRun" class="empty">
        {{ t("timeline.selectRunHint") }}
      </div>
      <div v-else class="timeline-track">
        <div class="timeline-item timeline-goal">
          <div class="timeline-avatar">{{ t("timeline.you") }}</div>
          <div class="timeline-card">
            <div class="timeline-title">{{ t("timeline.goal") }}</div>
            <div class="timeline-text">
              {{ props.currentRun.goal || t("timeline.noGoal") }}
            </div>
          </div>
        </div>
        <div v-if="!orderedSteps.length" class="empty">
          {{ t("timeline.noSteps") }}
        </div>
        <div
          v-for="(step, index) in orderedSteps"
          :key="step.id"
          class="timeline-item timeline-step"
          :class="{ active: step.id === props.selectedStepId }"
        >
          <button
            class="timeline-step-header"
            type="button"
            @click="emit('select-step', step.id)"
          >
            <div>
              <div class="timeline-step-title">
                {{ t("timeline.step", { index: index + 1 }) }} · {{ stepTitle(step) }}
              </div>
              <div class="timeline-step-meta">
                {{ stepMeta(step) }}
              </div>
            </div>
            <span class="status-badge" :class="stepStatus(step)">
              {{ stepStatusLabel(step) }}
            </span>
          </button>
          <div
            v-if="step.id === props.selectedStepId"
            class="timeline-step-body"
          >
            <details class="evidence-details" open>
              <summary>{{ t("timeline.evidence") }}</summary>
              <div v-if="!props.currentStep" class="evidence-empty">
                {{ t("timeline.evidenceSelect") }}
              </div>
              <div v-else-if="!evidenceAvailable" class="evidence-empty">
                {{ t("timeline.evidenceNone") }}
              </div>
              <div v-else class="evidence-grid">
                <div
                  v-for="item in evidenceItems"
                  :key="item.key"
                  class="evidence-card"
                >
                  <div class="evidence-label">{{ item.label }}</div>
                  <div class="evidence-frame">
                    <img
                      v-if="item.url"
                      class="evidence-img"
                      :src="item.url"
                      :alt="item.label"
                    />
                    <div v-else class="evidence-empty">
                      {{ item.emptyLabel }}
                    </div>
                  </div>
                </div>
              </div>
            </details>
            <details open>
              <summary>{{ t("timeline.decision") }}</summary>
              <pre>{{ props.decisionText }}</pre>
            </details>
            <details>
              <summary>{{ t("timeline.prompt") }}</summary>
              <pre>{{ props.promptText }}</pre>
            </details>
            <details>
              <summary>{{ t("timeline.response") }}</summary>
              <pre>{{ props.responseText }}</pre>
            </details>
            <details>
              <summary>{{ t("timeline.context") }}</summary>
              <pre>{{ props.contextText }}</pre>
            </details>
            <details>
              <summary>{{ t("timeline.verification") }}</summary>
              <pre>{{ props.verificationText }}</pre>
            </details>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { RunMeta, StepDetails, StepSummary } from "../api/types";
import { apiUrl } from "../client/http";

const props = defineProps<{
  runs: RunMeta[];
  currentRun: RunMeta | null;
  currentStep: StepDetails | null;
  selectedRunId: string | null;
  steps: StepSummary[];
  selectedStepId: string | null;
  decisionText: string;
  promptText: string;
  responseText: string;
  contextText: string;
  verificationText: string;
}>();

const emit = defineEmits<{
  (e: "select-run", runId: string): void;
  (e: "select-step", stepId: string): void;
}>();

const { t } = useI18n();

const search = ref("");
const activeRunId = ref(props.selectedRunId || "");
const showSwitcher = ref(false);

const evidenceItems = computed(() => {
  if (!props.currentStep) {
    return [];
  }
  const before =
    props.currentStep.step_screen_url || props.currentStep.screen_url || "";
  const after = props.currentStep.step_after_url || "";
  const cacheBust = (url?: string) => (url ? `${apiUrl(url)}?t=${Date.now()}` : "");
  return [
    {
      key: "before",
      label: t("timeline.before"),
      emptyLabel: t("timeline.noBefore"),
      url: cacheBust(before),
    },
    {
      key: "after",
      label: t("timeline.after"),
      emptyLabel: t("timeline.noAfter"),
      url: cacheBust(after),
    },
  ];
});

const evidenceAvailable = computed(() =>
  evidenceItems.value.some((item) => item.url),
);

watch(
  () => props.selectedRunId,
  (next) => {
    activeRunId.value = next || "";
  },
);

const filteredRuns = computed(() => {
  const needle = search.value.trim().toLowerCase();
  if (!needle) {
    return props.runs;
  }
  return props.runs.filter((run) => {
    const haystack = `${run.id} ${run.goal || ""} ${run.device_id || ""} ${run.device || ""}`.toLowerCase();
    return haystack.includes(needle);
  });
});

const orderedSteps = computed(() => {
  if (!props.steps.length) {
    return [];
  }
  return [...props.steps].sort((a, b) => a.id.localeCompare(b.id));
});

function handleRunChange() {
  if (!activeRunId.value) {
    return;
  }
  emit("select-run", activeRunId.value);
  showSwitcher.value = false;
}

function runOptionLabel(run: RunMeta) {
  const device = run.device_id || run.device;
  const parts = [run.goal || run.id];
  if (device) {
    parts.push(device);
  }
  return parts.join(" · ");
}

function formatTime(epochSeconds?: number) {
  if (!epochSeconds) {
    return "-";
  }
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleTimeString();
}

function runMetaLabel(run: RunMeta) {
  const parts = [run.id];
  if (run.status) {
    parts.push(formatRunStatus(run.status));
  }
  const device = run.device_id || run.device;
  if (device) {
    parts.push(device);
  }
  return parts.join(" · ");
}

function formatRunStatus(status: string) {
  const key = status.toLowerCase();
  if (["running", "finished", "failed", "stopping", "stopped", "idle"].includes(key)) {
    return t(`status.${key}`);
  }
  return status;
}

function stepTitle(step: StepSummary) {
  const goal = step.decision?.goal;
  if (goal) {
    return goal;
  }
  if (step.step_id) {
    return step.step_id;
  }
  return step.id.slice(0, 8);
}

function stepMeta(step: StepSummary) {
  const parts: string[] = [];
  parts.push(step.id.slice(0, 6));
  if (step.updated_time) {
    parts.push(formatTime(step.updated_time));
  }
  if (step.decision?.decision_mode) {
    parts.push(step.decision.decision_mode);
  }
  if (Number.isFinite(step.decision?.attempt)) {
    parts.push(t("timeline.tryLabel", { attempt: step.decision?.attempt }));
  }
  if (step.decision?.stop_reason) {
    parts.push(step.decision.stop_reason);
  }
  return parts.join(" · ");
}

function stepStatus(step: StepSummary) {
  if (step.decision?.done) {
    return "done";
  }
  return "pending";
}

function stepStatusLabel(step: StepSummary) {
  const status = stepStatus(step);
  return t(`status.${status}`);
}
</script>
