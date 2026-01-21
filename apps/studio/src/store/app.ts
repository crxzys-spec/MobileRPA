import { defineStore } from "pinia";
import { ref } from "vue";

export const useAppStore = defineStore("app", () => {
  const errorMessage = ref("");

  function setError(error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : String(error);
  }

  function clearError() {
    errorMessage.value = "";
  }

  return { errorMessage, setError, clearError };
});
