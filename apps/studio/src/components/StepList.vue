<template>
  <section class="panel">
    <div class="panel-header">
      <h2>{{ t("list.steps") }}</h2>
      <div class="pill status-pill" :class="props.runStatus">
        {{ runStatusLabel }}
      </div>
    </div>
    <div class="list">
      <div v-if="!props.steps.length" class="empty">{{ t("list.noSteps") }}</div>
      <div
        v-for="(step, index) in props.steps"
        :key="step.id"
        class="list-item"
        :class="{ active: step.id === props.selectedStepId }"
        :style="{ animationDelay: `${index * 0.03}s` }"
        @click="emit('select', step.id)"
      >
        <div class="title">{{ buildStepTitle(step) }}</div>
        <div class="meta">{{ buildStepMetaLine(step) }}</div>
        <div class="status-badge" :class="buildStepStatus(step)">
          {{ stepStatusLabel(step) }}
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { StepDetails, StepSummary } from "../api/types";

const props = defineProps<{
  steps: StepSummary[];
  selectedStepId: string | null;
  runStatus: string;
}>();

const emit = defineEmits<{
  (e: "select", stepId: string): void;
}>();

const { t } = useI18n();

const runStatusLabel = computed(() => {
  const status = (props.runStatus || "idle").toLowerCase();
  if (["running", "finished", "failed", "stopping", "stopped", "idle"].includes(status)) {
    return t(`status.${status}`);
  }
  return props.runStatus;
});

function buildStepTitle(step?: StepSummary | StepDetails | null) {
  const decision = step?.decision || {};
  return decision.goal || step?.id || t("list.step");
}

function buildStepMetaLine(step?: StepSummary | StepDetails | null) {
  const decision = step?.decision || {};
  const parts: string[] = [];
  if (decision.decision_mode) {
    parts.push(decision.decision_mode);
  }
  const actionCount = Array.isArray(decision.actions)
    ? decision.actions.length
    : 0;
  if (actionCount) {
    parts.push(t("list.actions", { count: actionCount }));
  }
  if (step?.has_screen) {
    parts.push(t("list.screen"));
  }
  return parts.length ? parts.join(" | ") : t("list.noDecision");
}

function buildStepStatus(step?: StepSummary | StepDetails | null) {
  const decision = step?.decision || {};
  if (decision.done === true) {
    return "done";
  }
  if (decision.done === false) {
    return "pending";
  }
  return "pending";
}

function stepStatusLabel(step?: StepSummary | StepDetails | null) {
  const status = buildStepStatus(step);
  return t(`status.${status}`);
}
</script>
