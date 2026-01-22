<template>
  <section class="panel console">
    <form class="console-form" @submit.prevent="emit('submit')">
      <label class="field console-goal">
        <span>{{ t("form.goal") }}</span>
        <textarea
          v-model.trim="form.goal"
          :placeholder="t('form.goalPlaceholder')"
          rows="3"
          required
        ></textarea>
      </label>
      <div class="console-actions">
        <div class="console-actions-primary">
          <button
            class="primary icon-btn"
            type="submit"
            :disabled="props.runSubmitting"
            :aria-label="t('form.run')"
            :title="t('form.run')"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <polygon class="icon-fill" points="8,5 19,12 8,19" />
            </svg>
          </button>
          <button
            v-if="isRunning"
            class="ghost icon-btn"
            type="button"
            :aria-label="t('form.stop')"
            :title="t('form.stop')"
            @click="emit('stop')"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect class="icon-fill" x="7" y="7" width="10" height="10" rx="2" />
            </svg>
          </button>
        </div>
        <div class="console-actions-toggles">
          <label class="toggle">
            <input v-model="form.execute" type="checkbox" />
            <span>{{ t("form.execute") }}</span>
          </label>
          <label class="toggle">
            <input v-model="form.plan" type="checkbox" />
            <span>{{ t("form.plan") }}</span>
          </label>
        </div>
      </div>
      <details class="console-settings">
        <summary>{{ t("form.advanced") }}</summary>
        <div class="console-grid">
          <label class="field">
            <span>{{ t("form.maxSteps") }}</span>
            <input v-model.number="form.maxSteps" type="number" min="1" />
          </label>
          <label class="field" :class="{ disabled: !form.plan }">
            <span>{{ t("form.planSteps") }}</span>
            <input
              v-model.number="form.planSteps"
              type="number"
              min="1"
              :disabled="!form.plan"
            />
          </label>
          <label class="field" :class="{ disabled: !form.plan }">
            <span>{{ t("form.planVerify") }}</span>
            <select v-model="form.planVerify" :disabled="!form.plan">
              <option value="llm">{{ t("form.planVerifyOptions.llm") }}</option>
              <option value="none">{{ t("form.planVerifyOptions.none") }}</option>
            </select>
          </label>
          <label class="field">
            <span>{{ t("form.device") }}</span>
            <select v-model="form.device">
              <option value="">{{ t("form.auto") }}</option>
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
        </div>
        <div class="toggle-group console-toggles">
          <label class="toggle">
            <input v-model="form.skills" type="checkbox" />
            <span>{{ t("form.skills") }}</span>
          </label>
          <label class="toggle">
            <input v-model="form.textOnly" type="checkbox" />
            <span>{{ t("form.textOnly") }}</span>
          </label>
          <label class="toggle" :class="{ disabled: !form.plan }">
            <input v-model="form.planResume" type="checkbox" :disabled="!form.plan" />
            <span>{{ t("form.planResume") }}</span>
          </label>
        </div>
      </details>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { Device } from "../api/types";

type RunFormState = {
  goal: string;
  maxSteps: number;
  planSteps: number;
  planVerify: string;
  device: string;
  execute: boolean;
  plan: boolean;
  skills: boolean;
  textOnly: boolean;
  planResume: boolean;
};

const props = defineProps<{
  devices: Device[];
  runSubmitting: boolean;
  runStatus?: string;
}>();

const { t } = useI18n();

const form = defineModel<RunFormState>("form", { required: true });

const emit = defineEmits<{
  (e: "submit"): void;
  (e: "stop"): void;
}>();

const isRunning = computed(() => props.runStatus === "running");

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
</script>
