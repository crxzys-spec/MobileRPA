<template>
  <section class="panel">
    <div class="panel-header">
      <h2>{{ t("list.runs") }}</h2>
      <button class="ghost" type="button" @click="emit('refresh')">
        {{ t("list.refresh") }}
      </button>
    </div>
    <div class="list">
      <div v-if="!props.runs.length" class="empty">{{ t("list.noRuns") }}</div>
      <div
        v-for="(run, index) in props.runs"
        :key="run.id"
        class="list-item"
        :class="{ active: run.id === props.selectedRunId }"
        :style="{ animationDelay: `${index * 0.03}s` }"
        @click="emit('select', run.id)"
      >
        <div class="title">{{ run.goal || run.id || t("list.run") }}</div>
        <div class="meta">{{ buildRunMeta(run) }}</div>
        <div class="status-badge" :class="normalizeStatus(run?.status)">
          {{ runStatusLabel(run?.status) }}
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { RunMeta } from "../api/types";

const props = defineProps<{
  runs: RunMeta[];
  selectedRunId: string | null;
}>();

const emit = defineEmits<{
  (e: "refresh"): void;
  (e: "select", runId: string): void;
}>();

const { t } = useI18n();

function normalizeStatus(value?: string) {
  const status = (value || "idle").toString().toLowerCase();
  if (["running", "finished", "failed", "stopping", "stopped"].includes(status)) {
    return status;
  }
  return "idle";
}

function runStatusLabel(value?: string) {
  const status = normalizeStatus(value);
  return t(`status.${status}`);
}

function formatTime(epochSeconds?: number) {
  if (!epochSeconds) {
    return "-";
  }
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleString();
}

function buildRunMeta(run?: RunMeta | null) {
  const parts = [] as string[];
  if (run?.id) {
    parts.push(run.id);
  }
  const deviceLabel = run?.device_id || run?.device;
  if (deviceLabel) {
    parts.push(deviceLabel);
  }
  if (run?.updated_time || run?.start_time) {
    parts.push(formatTime(run.updated_time || run.start_time));
  }
  return parts.join(" | ");
}
</script>
