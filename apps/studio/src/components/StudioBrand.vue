<template>
  <section class="panel brand-panel">
    <button
      class="brand-toggle"
      type="button"
      :aria-label="props.collapsed ? t('brand.expand') : t('brand.collapse')"
      :title="props.collapsed ? t('brand.expand') : t('brand.collapse')"
      @click="emit('toggle')"
    >
      <span class="brand-mark"></span>
      <span class="brand-text">
        <span class="brand-title">{{ t("brand.title") }}</span>
        <span class="brand-subtitle">{{ t("brand.subtitle") }}</span>
      </span>
    </button>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";

const props = defineProps<{
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle"): void;
}>();

const { t } = useI18n();
</script>
