<template>
  <section class="panel viewer">
    <div class="viewer-header">
      <div>
        <div class="viewer-title">{{ t("screen.title") }}</div>
        <div class="viewer-meta">{{ props.metaText }}</div>
      </div>
      <div class="viewer-tools">
        <button
          class="chip screen-toggle"
          :class="{ active: screenMode === 'before' }"
          type="button"
          @click="setScreenMode('before')"
        >
          {{ t("screen.before") }}
        </button>
        <button
          class="chip screen-toggle"
          :class="{ active: screenMode === 'after' }"
          type="button"
          @click="setScreenMode('after')"
        >
          {{ t("screen.after") }}
        </button>
      </div>
    </div>
    <div class="screen-frame">
      <div class="screen-empty" :class="{ hidden: screenHasImage }">
        {{ screenMessage }}
      </div>
      <img
        :src="screenSrc"
        class="screen-img"
        :class="{ hidden: !screenHasImage }"
        :alt="t('screen.title')"
        @load="onScreenLoad"
        @error="onScreenError"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { StepDetails } from "../api/types";
import { apiUrl } from "../client/http";

const props = defineProps<{
  currentStep: StepDetails | null;
  metaText: string;
}>();

const { t, locale } = useI18n();

const screenMode = defineModel<"before" | "after">("screenMode", {
  required: true,
});

const screenSrc = ref("");
const screenFallback = ref("");
const screenHasImage = ref(false);
const screenMessage = ref(t("screen.noScreen"));
const screenTriedFallback = ref(false);

function setScreenMode(mode: "before" | "after") {
  screenMode.value = mode;
}

function updateScreen() {
  const step = props.currentStep;
  if (!step) {
    screenSrc.value = "";
    screenFallback.value = "";
    screenHasImage.value = false;
    screenTriedFallback.value = false;
    screenMessage.value = t("screen.noScreen");
    return;
  }
  const before = step.step_screen_url;
  const after = step.step_after_url;
  const primary = screenMode.value === "after" ? after : before;
  const fallback = screenMode.value === "after" ? before : after;
  if (!primary && !fallback) {
    screenSrc.value = "";
    screenFallback.value = "";
    screenHasImage.value = false;
    screenTriedFallback.value = false;
    screenMessage.value = t("screen.noImage");
    return;
  }
  screenHasImage.value = false;
  screenTriedFallback.value = false;
  screenMessage.value = t("screen.loading");
  const cacheBust = (url?: string) =>
    url ? `${apiUrl(url)}?t=${Date.now()}` : "";
  screenFallback.value = fallback ? cacheBust(fallback) : "";
  screenSrc.value = primary ? cacheBust(primary) : screenFallback.value;
}

function onScreenLoad() {
  screenHasImage.value = true;
}

function onScreenError() {
  if (
    !screenTriedFallback.value &&
    screenFallback.value &&
    screenSrc.value !== screenFallback.value
  ) {
    screenTriedFallback.value = true;
    screenSrc.value = screenFallback.value;
    return;
  }
  screenHasImage.value = false;
  screenMessage.value = t("screen.noImage");
}

watch([() => props.currentStep, screenMode, locale], updateScreen, { immediate: true });
</script>
