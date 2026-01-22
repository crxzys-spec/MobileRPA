<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark"></span>
      <div>
        <div class="brand-title">{{ t("topbar.title") }}</div>
        <div class="brand-subtitle">{{ t("topbar.subtitle") }}</div>
      </div>
    </div>
    <form class="run-form" @submit.prevent="emit('submit')">
      <label class="field">
        <span>{{ t("form.goal") }}</span>
        <input
          v-model.trim="form.goal"
          type="text"
          :placeholder="t('form.goalPlaceholder')"
          required
        />
      </label>
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
      <div class="toggle-group">
        <label class="toggle">
          <input v-model="form.execute" type="checkbox" />
          <span>{{ t("form.execute") }}</span>
        </label>
        <label class="toggle">
          <input v-model="form.plan" type="checkbox" />
          <span>{{ t("form.plan") }}</span>
        </label>
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
      <button class="primary" type="submit" :disabled="props.runSubmitting">
        {{ t("form.run") }}
      </button>
    </form>
  </header>
</template>

<script setup lang="ts">
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
}>();

const form = defineModel<RunFormState>("form", { required: true });

const emit = defineEmits<{ (e: "submit"): void }>();

const { t } = useI18n();

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
