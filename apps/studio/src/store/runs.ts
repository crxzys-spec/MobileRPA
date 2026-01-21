import { defineStore } from "pinia";
import { ref } from "vue";

import type {
  RunLogResponse,
  RunMeta,
  RunRequest,
  StepDetails,
  StepSummary,
} from "../api/types";
import { apiUrl } from "../client/http";
import { runsService } from "../service/runs";
import { useAppStore } from "./app";

export const useRunsStore = defineStore("runs", () => {
  const app = useAppStore();

  const runs = ref<RunMeta[]>([]);
  const steps = ref<StepSummary[]>([]);
  const selectedRunId = ref<string | null>(null);
  const selectedStepId = ref<string | null>(null);
  const currentRun = ref<RunMeta | null>(null);
  const currentStep = ref<StepDetails | null>(null);
  const runLog = ref<RunLogResponse | null>(null);
  const runLogMessage = ref("No log loaded.");
  const logLive = ref(false);
  const logStatus = ref("idle");
  const logAuto = ref(true);
  const logMaxLines = 800;
  const runLogLines = ref<string[]>([]);
  const screenMode = ref<"before" | "after">("before");
  const activeTab = ref<"decision" | "prompt" | "response" | "context">(
    "decision",
  );
  const pollId = ref<number | null>(null);
  const pollRunId = ref<string | null>(null);
  let logSource: EventSource | null = null;
  let logRetryTimer: number | null = null;
  const logRetryBaseMs = 800;
  const logRetryMaxMs = 8000;
  const logRetryAttempt = ref(0);

  function applyRun(
    run: RunMeta,
    { keepStep = true }: { keepStep?: boolean } = {},
  ) {
    currentRun.value = run;
    steps.value = Array.isArray(run?.steps) ? run.steps : [];
    const stepIds = new Set(steps.value.map((step) => step.id));
    const currentStepId = selectedStepId.value;
    if (!keepStep || !currentStepId || !stepIds.has(currentStepId)) {
      selectedStepId.value =
        steps.value.length > 0 ? steps.value[steps.value.length - 1].id : null;
    }
  }

  function applyStep(step: StepDetails) {
    currentStep.value = step;
  }

  function clearRunView() {
    stopLogStream("idle");
    currentRun.value = null;
    steps.value = [];
    selectedStepId.value = null;
    runLog.value = null;
    runLogMessage.value = "No log loaded.";
    runLogLines.value = [];
    clearStepView();
  }

  function clearStepView() {
    currentStep.value = null;
    selectedStepId.value = null;
  }

  function handlePolling(run?: RunMeta | null) {
    const status = (run?.status || "idle").toString().toLowerCase();
    if (status === "running" && run?.id) {
      startPolling(run.id);
      return;
    }
    stopPolling();
  }

  function startPolling(runId: string) {
    if (pollId.value && pollRunId.value === runId) {
      return;
    }
    stopPolling();
    pollRunId.value = runId;
    pollId.value = window.setInterval(() => {
      refreshAll({ keepStep: true }).catch(() => {});
    }, 2500);
  }

  function stopPolling() {
    if (pollId.value !== null) {
      window.clearInterval(pollId.value);
    }
    pollId.value = null;
    pollRunId.value = null;
  }

  function splitLines(text: string) {
    if (!text) {
      return [];
    }
    const lines = text.replace(/\r/g, "").split("\n");
    if (lines.length && lines[lines.length - 1] === "") {
      lines.pop();
    }
    return lines;
  }

  function applyLogSnapshot(log: RunLogResponse) {
    const lines = splitLines(log.text);
    runLogLines.value = lines.slice(-logMaxLines);
    runLog.value = {
      ...log,
      text: runLogLines.value.join("\n"),
      lines: runLogLines.value.length,
      truncated: log.total_lines > runLogLines.value.length,
    };
  }

  function appendLogText(text: string, totalLines: number, reset = false) {
    if (reset) {
      runLogLines.value = [];
    }
    const newLines = splitLines(text);
    if (newLines.length) {
      runLogLines.value.push(...newLines);
      if (runLogLines.value.length > logMaxLines) {
        runLogLines.value = runLogLines.value.slice(-logMaxLines);
      }
    }
    const textOut = runLogLines.value.join("\n");
    runLog.value = {
      run_id: selectedRunId.value || "",
      text: textOut,
      lines: runLogLines.value.length,
      total_lines: Math.max(totalLines, runLogLines.value.length),
      truncated: totalLines > runLogLines.value.length,
      updated_time: Date.now(),
      log_path: runLog.value?.log_path,
    };
  }

  function clearLogRetry() {
    if (logRetryTimer) {
      window.clearTimeout(logRetryTimer);
    }
    logRetryTimer = null;
    logRetryAttempt.value = 0;
  }

  function closeLogSource() {
    if (logSource) {
      logSource.close();
    }
    logSource = null;
  }

  function scheduleLogReconnect() {
    if (!logAuto.value || !logLive.value) {
      return;
    }
    if (logRetryTimer) {
      return;
    }
    const attempt = logRetryAttempt.value;
    const delay = Math.min(
      logRetryBaseMs * Math.pow(2, attempt),
      logRetryMaxMs,
    );
    logStatus.value = `reconnecting in ${Math.ceil(delay / 1000)}s`;
    logRetryTimer = window.setTimeout(() => {
      logRetryTimer = null;
      logRetryAttempt.value += 1;
      startLogStream();
    }, delay);
  }

  function stopLogStream(status = "idle") {
    closeLogSource();
    clearLogRetry();
    logLive.value = false;
    logStatus.value = status;
  }

  function startLogStream() {
    const runId = selectedRunId.value;
    if (!runId) {
      runLogMessage.value = "No run selected.";
      logStatus.value = "idle";
      return;
    }
    if (logSource) {
      return;
    }
    clearLogRetry();
    logStatus.value = "connecting";
    logLive.value = true;
    const fromLine = runLog.value?.total_lines ?? 0;
    const url = apiUrl(
      `/api/runs/${encodeURIComponent(runId)}/log/stream?from_line=${fromLine}`,
    );
    logSource = new EventSource(url);
    logSource.onopen = () => {
      logStatus.value = "live";
      logRetryAttempt.value = 0;
    };
    logSource.onerror = () => {
      closeLogSource();
      if (logAuto.value && logLive.value) {
        scheduleLogReconnect();
      } else {
        logStatus.value = "error";
      }
    };
    logSource.addEventListener("log", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data);
        const totalLines = Number(payload.total_lines || 0);
        appendLogText(payload.text || "", totalLines, Boolean(payload.reset));
      } catch (_error) {
        logStatus.value = "error";
      }
    });
  }

  function toggleLogStream() {
    if (logLive.value) {
      logAuto.value = false;
      stopLogStream("paused");
      return;
    }
    logAuto.value = true;
    startLogStream();
  }

  async function refreshAll({
    selectNewest = false,
    keepStep = true,
  }: {
    selectNewest?: boolean;
    keepStep?: boolean;
  } = {}) {
    app.clearError();
    try {
      runs.value = await runsService.listRuns();
      if (selectNewest && runs.value.length && !selectedRunId.value) {
        selectedRunId.value = runs.value[0].id;
      }
      const runId = selectedRunId.value;
      const selectedExists = runs.value.some((run) => run.id === runId);
      if (!runId || !selectedExists) {
        selectedRunId.value = null;
        clearRunView();
        return;
      }
      const run = await runsService.getRun(runId);
      applyRun(run, { keepStep });
      if (selectedStepId.value) {
        await selectStep(selectedStepId.value);
      } else {
        clearStepView();
      }
      const status = (run?.status || "idle").toString().toLowerCase();
      if (status === "running") {
        await refreshRunLog();
        if (logAuto.value) {
          startLogStream();
        }
      } else if (logLive.value && logAuto.value) {
        stopLogStream("idle");
      }
      handlePolling(run);
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function selectRun(runId: string) {
    app.clearError();
    try {
      stopLogStream("idle");
      selectedRunId.value = runId;
      selectedStepId.value = null;
      runLog.value = null;
      runLogMessage.value = "No log loaded.";
      await refreshAll({ keepStep: false });
      await refreshRunLog();
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function selectStep(stepId: string) {
    app.clearError();
    try {
      const runId = selectedRunId.value;
      if (!runId || !stepId) {
        clearStepView();
        return;
      }
      selectedStepId.value = stepId;
      const step = await runsService.getStep(runId, stepId);
      applyStep(step);
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function startRun(payload: RunRequest) {
    app.clearError();
    try {
      stopLogStream("idle");
      const result = await runsService.startRun(payload);
      selectedRunId.value = result.id;
      selectedStepId.value = null;
      runLog.value = null;
      runLogMessage.value = "No log loaded.";
      await refreshAll({ keepStep: false });
      await refreshRunLog();
      return result;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function stopRun(runId: string) {
    app.clearError();
    try {
      const result = await runsService.stopRun(runId);
      await refreshAll({ keepStep: true });
      return result;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  function cleanup() {
    stopPolling();
    stopLogStream("idle");
  }

  async function refreshRunLog(limit = 200) {
    const runId = selectedRunId.value;
    if (!runId) {
      runLog.value = null;
      runLogMessage.value = "No run selected.";
      return null;
    }
    try {
      const log = await runsService.getRunLog(runId, limit);
      applyLogSnapshot(log);
      runLogMessage.value = "";
      return log;
    } catch (error) {
      runLog.value = null;
      runLogMessage.value = "Log unavailable.";
      return null;
    }
  }

  return {
    runs,
    steps,
    selectedRunId,
    selectedStepId,
    currentRun,
    currentStep,
    runLog,
    runLogMessage,
    logLive,
    logStatus,
    screenMode,
    activeTab,
    pollId,
    pollRunId,
    refreshAll,
    selectRun,
    selectStep,
    startRun,
    stopRun,
    refreshRunLog,
    startLogStream,
    stopLogStream,
    toggleLogStream,
    startPolling,
    stopPolling,
    cleanup,
  };
});
