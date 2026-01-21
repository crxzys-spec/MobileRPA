<template>
  <section class="panel detail">
    <div class="tabs">
      <button
        class="tab"
        :class="{ active: activeTab === 'decision' }"
        type="button"
        @click="activeTab = 'decision'"
      >
        {{ t("decisionTabs.decision") }}
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'prompt' }"
        type="button"
        @click="activeTab = 'prompt'"
      >
        {{ t("decisionTabs.prompt") }}
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'response' }"
        type="button"
        @click="activeTab = 'response'"
      >
        {{ t("decisionTabs.response") }}
      </button>
      <button
        class="tab"
        :class="{ active: activeTab === 'context' }"
        type="button"
        @click="activeTab = 'context'"
      >
        {{ t("decisionTabs.context") }}
      </button>
    </div>
    <div class="tab-content">
      <pre v-show="activeTab === 'decision'">{{ props.decisionText }}</pre>
      <pre v-show="activeTab === 'prompt'">{{ props.promptText }}</pre>
      <pre v-show="activeTab === 'response'">{{ props.responseText }}</pre>
      <pre v-show="activeTab === 'context'">{{ props.contextText }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";

const props = defineProps<{
  decisionText: string;
  promptText: string;
  responseText: string;
  contextText: string;
}>();

const { t } = useI18n();

const activeTab = defineModel<"decision" | "prompt" | "response" | "context">(
  "activeTab",
  { required: true },
);
</script>
