(() => {
  "use strict";

  const state = {
    runs: [],
    steps: [],
    selectedRunId: null,
    selectedStepId: null,
    currentStep: null,
    currentRun: null,
    screenMode: "before",
    pollId: null,
    pollRunId: null,
    devices: [],
    liveConnections: new Map(),
    webrtcConfig: null,
  };
  window.__webrtcState = state;
  window.__webrtcConnections = state.liveConnections;

  const elements = {
    runForm: document.getElementById("run-form"),
    goal: document.getElementById("goal"),
    maxSteps: document.getElementById("max-steps"),
    planSteps: document.getElementById("plan-steps"),
    planVerify: document.getElementById("plan-verify"),
    device: document.getElementById("device"),
    execute: document.getElementById("execute"),
    plan: document.getElementById("plan"),
    skills: document.getElementById("skills"),
    textOnly: document.getElementById("text-only"),
    planResume: document.getElementById("plan-resume"),
    refreshRuns: document.getElementById("refresh-runs"),
    refreshDevices: document.getElementById("refresh-devices"),
    runs: document.getElementById("runs"),
    steps: document.getElementById("steps"),
    liveGrid: document.getElementById("live-grid"),
    runStatus: document.getElementById("run-status"),
    stepMeta: document.getElementById("step-meta"),
    screen: document.getElementById("screen"),
    screenEmpty: document.getElementById("screen-empty"),
    runDetails: document.getElementById("run-details"),
    verification: document.getElementById("verification"),
    stopRun: document.getElementById("stop-run"),
    tabButtons: Array.from(document.querySelectorAll(".tab")),
    tabDecision: document.getElementById("tab-decision"),
    tabPrompt: document.getElementById("tab-prompt"),
    tabResponse: document.getElementById("tab-response"),
    tabContext: document.getElementById("tab-context"),
    screenModeButtons: Array.from(document.querySelectorAll(".screen-toggle")),
  };

  const api = {
    listRuns: () => fetchJson("/api/runs"),
    listDevices: () => fetchJson("/api/devices"),
    getRun: (runId) => fetchJson(`/api/runs/${encodeURIComponent(runId)}`),
    getStep: (runId, stepId) =>
      fetchJson(
        `/api/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}`,
      ),
    getWebRTCConfig: () => fetchJson("/api/webrtc/config"),
    startRun: (payload) =>
      fetchJson("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    webrtcOffer: (payload) =>
      fetchJson("/api/webrtc/offer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    stopRun: (runId) =>
      fetchJson(`/api/runs/${encodeURIComponent(runId)}/stop`, {
        method: "POST",
      }),
  };

  function normalizeStatus(value) {
    const status = (value || "idle").toString().toLowerCase();
    if (["running", "finished", "failed", "stopping", "stopped"].includes(status)) {
      return status;
    }
    return "idle";
  }

  function normalizeDeviceStatus(value) {
    return (value || "unknown").toString().toLowerCase();
  }

  function deviceStatusClass(value) {
    const status = normalizeDeviceStatus(value);
    if (["device", "offline", "unauthorized"].includes(status)) {
      return status;
    }
    return "unknown";
  }

  function formatTime(epochSeconds) {
    if (!epochSeconds) {
      return "-";
    }
    const date = new Date(epochSeconds * 1000);
    if (Number.isNaN(date.getTime())) {
      return "-";
    }
    return date.toLocaleString();
  }

  function formatJson(value) {
    if (value === null || value === undefined) {
      return "No data";
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return "Invalid JSON";
    }
  }

  function toPositiveInt(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
    return fallback;
  }

  function createText(tag, className, text) {
    const el = document.createElement(tag);
    if (className) {
      el.className = className;
    }
    el.textContent = text;
    return el;
  }

  function createEmpty(message) {
    return createText("div", "empty", message);
  }

  function setTab(tabName) {
    elements.tabButtons.forEach((button) => {
      const active = button.dataset.tab === tabName;
      button.classList.toggle("active", active);
    });
    elements.tabDecision.classList.toggle("hidden", tabName !== "decision");
    elements.tabPrompt.classList.toggle("hidden", tabName !== "prompt");
    elements.tabResponse.classList.toggle("hidden", tabName !== "response");
    elements.tabContext.classList.toggle("hidden", tabName !== "context");
  }

  function setDeviceOptions(devices) {
    if (!elements.device) {
      return;
    }
    const current = elements.device.value;
    elements.device.innerHTML = "";
    const autoOption = new Option("auto", "");
    elements.device.appendChild(autoOption);
    devices.forEach((device) => {
      const label = device.status
        ? `${device.id} (${device.status})`
        : device.id;
      const option = new Option(label, device.id);
      if (device.status && device.status !== "device") {
        option.disabled = true;
      }
      elements.device.appendChild(option);
    });
    if (current) {
      elements.device.value = current;
    }
  }

  async function ensureWebRTCConfig() {
    if (state.webrtcConfig) {
      return state.webrtcConfig;
    }
    try {
      state.webrtcConfig = await api.getWebRTCConfig();
    } catch (error) {
      state.webrtcConfig = { ice_servers: [] };
    }
    return state.webrtcConfig;
  }

  function buildIceServers(config) {
    const entries = Array.isArray(config?.ice_servers) ? config.ice_servers : [];
    const servers = [];
    entries.forEach((entry) => {
      if (!entry) {
        return;
      }
      if (typeof entry === "string") {
        servers.push({ urls: entry });
      } else if (entry.urls) {
        servers.push(entry);
      }
    });
    return servers;
  }

  function waitForIceGathering(pc) {
    if (pc.iceGatheringState === "complete") {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const handler = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", handler);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", handler);
    });
  }

  function isConnectionActive(deviceId, pc) {
    const connection = state.liveConnections.get(deviceId);
    return connection && connection.pc === pc;
  }

  function stopLiveStream(deviceId) {
    const connection = state.liveConnections.get(deviceId);
    if (connection) {
      connection.pc.ontrack = null;
      connection.pc.onconnectionstatechange = null;
      connection.pc.close();
    }
    state.liveConnections.delete(deviceId);
  }

  async function startWebRTCStream(deviceId, card) {
    const config = await ensureWebRTCConfig();
    const pc = new RTCPeerConnection({ iceServers: buildIceServers(config) });
    const connection = { pc, stream: null, status: "Connecting..." };
    state.liveConnections.set(deviceId, connection);
    applyLiveCardState(card, deviceId);

    const transceiver = pc.addTransceiver("video", { direction: "recvonly" });
    const capabilities =
      window.RTCRtpReceiver?.getCapabilities?.("video") || null;
    if (capabilities?.codecs?.length && transceiver.setCodecPreferences) {
      const preferred = [];
      const rest = [];
      const h264Payloads = new Set();
      capabilities.codecs.forEach((codec) => {
        if (codec.mimeType?.toLowerCase() === "video/h264") {
          preferred.push(codec);
          h264Payloads.add(codec.payloadType);
        }
      });
      capabilities.codecs.forEach((codec) => {
        if (
          codec.mimeType?.toLowerCase() === "video/rtx" &&
          h264Payloads.has(codec.parameters?.apt)
        ) {
          preferred.push(codec);
        }
      });
      capabilities.codecs.forEach((codec) => {
        if (!preferred.includes(codec)) {
          rest.push(codec);
        }
      });
      if (preferred.length) {
        transceiver.setCodecPreferences([...preferred, ...rest]);
        console.log(
          "[webrtc] codec preference",
          deviceId,
          preferred.map((codec) => codec.mimeType),
        );
      }
    }
    pc.ontrack = (event) => {
      if (!isConnectionActive(deviceId, pc)) {
        return;
      }
      const incoming = event.streams && event.streams[0];
      if (incoming) {
        connection.stream = incoming;
      } else {
        connection.stream = new MediaStream([event.track]);
      }
      connection.status = "Connected";
      applyLiveCardState(card, deviceId);
    };
    pc.onconnectionstatechange = () => {
      if (!isConnectionActive(deviceId, pc)) {
        return;
      }
      if (pc.connectionState === "connected") {
        connection.status = "Connected";
        applyLiveCardState(card, deviceId);
        return;
      }
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
        stopLiveStream(deviceId);
        applyLiveCardState(card, deviceId, "Stream error");
      }
      if (pc.connectionState === "closed") {
        stopLiveStream(deviceId);
        applyLiveCardState(card, deviceId);
      }
    };
    pc.onicecandidate = (event) => {
      const candidate = event.candidate ? event.candidate.candidate : null;
      console.log("[webrtc] ice candidate", deviceId, candidate);
    };
    pc.onicecandidateerror = (event) => {
      console.log("[webrtc] ice candidate error", deviceId, event);
    };
    pc.oniceconnectionstatechange = () => {
      console.log("[webrtc] ice state", deviceId, pc.iceConnectionState);
    };
    pc.onicegatheringstatechange = () => {
      console.log("[webrtc] ice gathering", deviceId, pc.iceGatheringState);
    };
    pc.onsignalingstatechange = () => {
      console.log("[webrtc] signaling", deviceId, pc.signalingState);
    };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    console.log("[webrtc] offer", deviceId, offer);
    await waitForIceGathering(pc);
    if (!isConnectionActive(deviceId, pc)) {
      return;
    }
    const answer = await api.webrtcOffer({
      device_id: deviceId,
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type,
    });
    if (!isConnectionActive(deviceId, pc)) {
      return;
    }
    console.log("[webrtc] answer", deviceId, answer);
    await pc.setRemoteDescription(answer);
    const receiver = pc.getTransceivers?.()[0]?.receiver;
    if (receiver?.getParameters) {
      console.log(
        "[webrtc] negotiated codecs",
        deviceId,
        receiver.getParameters().codecs,
      );
    }
  }

  function applyLiveCardState(card, deviceId, message) {
    const frame = card.querySelector(".live-frame");
    const video = card.querySelector(".live-stream");
    const placeholder = card.querySelector(".live-placeholder");
    const button = card.querySelector("button[data-action='toggle-stream']");
    const connection = state.liveConnections.get(deviceId);
    const active = Boolean(connection);

    if (!video || !placeholder || !button) {
      return;
    }

    if (!active) {
      if (video.srcObject) {
        video.srcObject = null;
      }
      if (frame) {
        frame.classList.remove("ready");
      }
      placeholder.textContent = message || "Stream stopped";
      placeholder.classList.remove("hidden");
      button.textContent = "Start";
      card.classList.remove("streaming");
      return;
    }

    button.textContent = "Stop";
    card.classList.add("streaming");
    if (connection.stream) {
      video.srcObject = connection.stream;
      video.play().catch(() => {});
      if (frame) {
        frame.classList.add("ready");
      }
      placeholder.classList.add("hidden");
      return;
    }

    if (frame) {
      frame.classList.remove("ready");
    }
    placeholder.textContent = connection.status || "Connecting...";
    placeholder.classList.remove("hidden");
  }

  function renderDevices(devices) {
    if (!elements.liveGrid) {
      return;
    }
    elements.liveGrid.innerHTML = "";
    setDeviceOptions(devices);

    if (!devices.length) {
      elements.liveGrid.appendChild(createEmpty("No devices detected."));
      return;
    }

    devices.forEach((device, index) => {
      const card = document.createElement("div");
      card.className = "live-card";
      card.dataset.deviceId = device.id;
      card.style.animationDelay = `${index * 0.03}s`;

      const header = document.createElement("div");
      header.className = "live-header";
      const title = createText("div", "live-title", device.id);
      const statusClass = deviceStatusClass(device.status);
      const badge = createText(
        "div",
        `status-badge ${statusClass}`,
        normalizeDeviceStatus(device.status),
      );
      header.append(title, badge);

      const frame = document.createElement("div");
      frame.className = "live-frame";
      const placeholder = createText("div", "live-placeholder", "Stream stopped");
      const video = document.createElement("video");
      video.className = "live-stream";
      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      frame.append(placeholder, video);

      const controls = document.createElement("div");
      controls.className = "live-controls";
      const button = createText("button", "ghost", "Start");
      button.dataset.action = "toggle-stream";
      if (device.status && device.status !== "device") {
        button.disabled = true;
        button.textContent = "Unavailable";
      }
      controls.appendChild(button);

      card.append(header, frame, controls);
      elements.liveGrid.appendChild(card);

      if (state.liveConnections.has(device.id)) {
        applyLiveCardState(card, device.id);
      }
    });
  }

  function setRunStatus(run) {
    const status = normalizeStatus(run?.status);
    elements.runStatus.textContent = status;
    elements.runStatus.className = `pill status-pill ${status}`;
  }

  function setStopButton(run) {
    const status = normalizeStatus(run?.status);
    elements.stopRun.disabled = status !== "running";
  }

  function buildRunMeta(run) {
    const parts = [];
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

  function buildStepMeta(step) {
    const decision = step?.decision || {};
    const parts = [];
    if (step?.step_id) {
      parts.push(step.step_id);
    }
    if (decision.decision_mode) {
      parts.push(decision.decision_mode);
    }
    if (Number.isFinite(decision.attempt)) {
      parts.push(`attempt ${decision.attempt}`);
    }
    if (decision.done === true) {
      parts.push("done");
    }
    if (decision.stop_reason) {
      parts.push(decision.stop_reason);
    }
    return parts.length ? parts.join(" | ") : "No step selected";
  }

  function buildStepTitle(step) {
    const decision = step?.decision || {};
    return decision.goal || step.id || "Step";
  }

  function buildStepMetaLine(step) {
    const decision = step?.decision || {};
    const parts = [];
    if (decision.decision_mode) {
      parts.push(decision.decision_mode);
    }
    const actionCount = Array.isArray(decision.actions)
      ? decision.actions.length
      : 0;
    if (actionCount) {
      parts.push(`${actionCount} actions`);
    }
    if (step?.has_screen) {
      parts.push("screen");
    }
    return parts.length ? parts.join(" | ") : "No decision";
  }

  function buildStepStatus(step) {
    const decision = step?.decision || {};
    if (decision.done === true) {
      return "done";
    }
    if (decision.done === false) {
      return "pending";
    }
    return "pending";
  }

  function buildVerificationPayload(step) {
    const decision = step?.decision || {};
    const payload = {};
    if (step?.verification) {
      payload.verification = step.verification;
    }
    if (decision.plan_verify) {
      payload.plan_verify = decision.plan_verify;
    }
    return Object.keys(payload).length ? payload : null;
  }

  function setScreenMode(mode) {
    state.screenMode = mode;
    elements.screenModeButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.screen === mode);
    });
    if (state.currentStep) {
      applyScreen(state.currentStep);
    }
  }

  function showScreen(primary, fallback) {
    const img = elements.screen;
    const empty = elements.screenEmpty;
    img.classList.add("hidden");
    empty.textContent = "Loading screenshot...";
    empty.classList.remove("hidden");

    if (!primary && !fallback) {
      empty.textContent = "No screenshot available";
      return;
    }

    const cacheBust = (url) => (url ? `${url}?t=${Date.now()}` : null);
    const primaryUrl = cacheBust(primary);
    const fallbackUrl = cacheBust(fallback);
    let triedFallback = false;

    img.onload = () => {
      img.classList.remove("hidden");
      empty.classList.add("hidden");
    };

    img.onerror = () => {
      if (!triedFallback && fallbackUrl) {
        triedFallback = true;
        img.src = fallbackUrl;
        return;
      }
      img.classList.add("hidden");
      empty.textContent = "No screenshot available";
      empty.classList.remove("hidden");
    };

    if (primaryUrl) {
      img.src = primaryUrl;
    } else if (fallbackUrl) {
      triedFallback = true;
      img.src = fallbackUrl;
    } else {
      empty.textContent = "No screenshot available";
    }
  }

  function applyScreen(step) {
    const before = step?.step_screen_url;
    const after = step?.step_after_url;
    const primary = state.screenMode === "after" ? after : before;
    const fallback = state.screenMode === "after" ? before : after;
    showScreen(primary, fallback);
  }

  function applyRun(run, { keepStep = true } = {}) {
    state.currentRun = run;
    state.steps = Array.isArray(run?.steps) ? run.steps : [];
    renderSteps(state.steps);
    setRunStatus(run);
    setStopButton(run);
    elements.runDetails.textContent = formatJson(run);

    const stepIds = new Set(state.steps.map((step) => step.id));
    if (!keepStep || !stepIds.has(state.selectedStepId)) {
      state.selectedStepId =
        state.steps.length > 0 ? state.steps[state.steps.length - 1].id : null;
    }
  }

  function applyStep(step) {
    state.currentStep = step;
    elements.stepMeta.textContent = buildStepMeta(step);
    elements.tabDecision.textContent = formatJson(step?.decision);
    elements.tabPrompt.textContent = step?.prompt || "No data";
    elements.tabResponse.textContent = step?.response || "No data";
    elements.tabContext.textContent = formatJson(step?.context);
    elements.verification.textContent = formatJson(buildVerificationPayload(step));
    applyScreen(step);
  }

  function renderRuns(runs) {
    elements.runs.innerHTML = "";
    if (!runs.length) {
      elements.runs.appendChild(createEmpty("No runs yet."));
      return;
    }

    runs.forEach((run, index) => {
      const item = document.createElement("div");
      item.className = "list-item";
      item.dataset.runId = run.id;
      if (run.id === state.selectedRunId) {
        item.classList.add("active");
      }
      item.style.animationDelay = `${index * 0.03}s`;

      const title = createText("div", "title", run.goal || run.id || "Run");
      const meta = createText("div", "meta", buildRunMeta(run));
      const status = normalizeStatus(run?.status);
      const badge = createText("div", `status-badge ${status}`, status);

      item.append(title, meta, badge);
      elements.runs.appendChild(item);
    });
  }

  function renderSteps(steps) {
    elements.steps.innerHTML = "";
    if (!steps.length) {
      elements.steps.appendChild(createEmpty("No steps yet."));
      return;
    }

    const ordered = [...steps].sort((a, b) => a.id.localeCompare(b.id));
    const display = ordered.slice().reverse();
    display.forEach((step, index) => {
      const item = document.createElement("div");
      item.className = "list-item";
      item.dataset.stepId = step.id;
      if (step.id === state.selectedStepId) {
        item.classList.add("active");
      }
      item.style.animationDelay = `${index * 0.03}s`;

      const title = createText("div", "title", buildStepTitle(step));
      const meta = createText("div", "meta", buildStepMetaLine(step));
      const status = buildStepStatus(step);
      const badge = createText("div", `status-badge ${status}`, status);

      item.append(title, meta, badge);
      elements.steps.appendChild(item);
    });
  }

  function toggleLiveStream(card) {
    const deviceId = card?.dataset?.deviceId;
    if (!deviceId) {
      return;
    }
    const connection = state.liveConnections.get(deviceId);
    if (connection) {
      stopLiveStream(deviceId);
      applyLiveCardState(card, deviceId);
      return;
    }
    startWebRTCStream(deviceId, card).catch((error) => {
      stopLiveStream(deviceId);
      applyLiveCardState(card, deviceId, "Stream error");
      showError(error);
    });
  }

  async function refreshDevices() {
    state.devices = await api.listDevices();
    const deviceIds = new Set(state.devices.map((device) => device.id));
    Array.from(state.liveConnections.keys()).forEach((deviceId) => {
      if (!deviceIds.has(deviceId)) {
        stopLiveStream(deviceId);
      }
    });
    renderDevices(state.devices);
  }

  function clearRunView() {
    elements.runDetails.textContent = "No run selected.";
    setRunStatus(null);
    setStopButton(null);
    state.steps = [];
    state.selectedStepId = null;
    renderSteps([]);
    clearStepView();
  }

  function clearStepView() {
    state.currentStep = null;
    state.selectedStepId = null;
    elements.stepMeta.textContent = "No step selected";
    elements.tabDecision.textContent = "No data";
    elements.tabPrompt.textContent = "No data";
    elements.tabResponse.textContent = "No data";
    elements.tabContext.textContent = "No data";
    elements.verification.textContent = "No data";
    elements.screen.classList.add("hidden");
    elements.screenEmpty.textContent = "No screenshot loaded";
    elements.screenEmpty.classList.remove("hidden");
  }

  async function refreshAll({ selectNewest = false, keepStep = true } = {}) {
    state.runs = await api.listRuns();
    renderRuns(state.runs);

    if (selectNewest && state.runs.length && !state.selectedRunId) {
      state.selectedRunId = state.runs[0].id;
    }

    const selectedExists = state.runs.some((run) => run.id === state.selectedRunId);
    if (!state.selectedRunId || !selectedExists) {
      state.selectedRunId = null;
      clearRunView();
      return;
    }

    const run = await api.getRun(state.selectedRunId);
    applyRun(run, { keepStep });

    if (state.selectedStepId) {
      await selectStep(state.selectedStepId);
    } else {
      clearStepView();
    }

    handlePolling(run);
  }

  async function selectRun(runId) {
    state.selectedRunId = runId;
    state.selectedStepId = null;
    await refreshAll({ keepStep: false });
  }

  async function selectStep(stepId) {
    if (!state.selectedRunId || !stepId) {
      clearStepView();
      return;
    }
    state.selectedStepId = stepId;
    renderSteps(state.steps);
    const step = await api.getStep(state.selectedRunId, stepId);
    applyStep(step);
  }

  function handlePolling(run) {
    const status = normalizeStatus(run?.status);
    if (status === "running") {
      startPolling(run.id);
    } else {
      stopPolling();
    }
  }

  function startPolling(runId) {
    if (state.pollId && state.pollRunId === runId) {
      return;
    }
    stopPolling();
    state.pollRunId = runId;
    state.pollId = window.setInterval(() => {
      refreshAll({ keepStep: true }).catch(showError);
    }, 2500);
  }

  function stopPolling() {
    if (state.pollId) {
      window.clearInterval(state.pollId);
    }
    state.pollId = null;
    state.pollRunId = null;
  }

  function setPlanControls() {
    const enabled = elements.plan.checked;
    elements.planSteps.disabled = !enabled;
    elements.planVerify.disabled = !enabled;
    elements.planResume.disabled = !enabled;

    const planFields = [elements.planSteps, elements.planVerify];
    planFields.forEach((input) => {
      const field = input.closest(".field");
      if (field) {
        field.classList.toggle("disabled", !enabled);
      }
    });

    const planToggle = elements.planResume.closest(".toggle");
    if (planToggle) {
      planToggle.classList.toggle("disabled", !enabled);
    }
  }

  function showError(error) {
    const message = error instanceof Error ? error.message : String(error);
    elements.runDetails.textContent = `Error: ${message}`;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        throw new Error("Invalid JSON response");
      }
    }
    if (!response.ok) {
      const detail = data && data.detail ? data.detail : response.statusText;
      throw new Error(detail || "Request failed");
    }
    return data;
  }

  async function handleRunSubmit(event) {
    event.preventDefault();
    const goal = elements.goal.value.trim();
    if (!goal) {
      return;
    }

    const payload = {
      goal,
      execute: elements.execute.checked,
      plan: elements.plan.checked,
      plan_max_steps: toPositiveInt(elements.planSteps.value, 5),
      plan_verify: elements.planVerify.value,
      plan_resume: elements.planResume.checked,
      max_steps: toPositiveInt(elements.maxSteps.value, 5),
      skills: elements.skills.checked,
      text_only: elements.textOnly.checked,
    };
    if (elements.device && elements.device.value) {
      payload.device = elements.device.value;
    }

    const submitButton = elements.runForm.querySelector("button[type='submit']");
    if (submitButton) {
      submitButton.disabled = true;
    }

    try {
      const result = await api.startRun(payload);
      state.selectedRunId = result.id;
      state.selectedStepId = null;
      await refreshAll({ keepStep: false });
    } catch (error) {
      showError(error);
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  }

  async function handleStopRun() {
    if (!state.selectedRunId) {
      return;
    }
    try {
      await api.stopRun(state.selectedRunId);
      await refreshAll({ keepStep: true });
    } catch (error) {
      showError(error);
    }
  }

  function bindEvents() {
    elements.runForm.addEventListener("submit", handleRunSubmit);
    elements.refreshRuns.addEventListener("click", () => {
      refreshAll({ keepStep: true }).catch(showError);
    });
    if (elements.refreshDevices) {
      elements.refreshDevices.addEventListener("click", () => {
        refreshDevices().catch(showError);
      });
    }
    elements.stopRun.addEventListener("click", handleStopRun);

    elements.runs.addEventListener("click", (event) => {
      const item = event.target.closest(".list-item");
      if (!item || !elements.runs.contains(item)) {
        return;
      }
      const runId = item.dataset.runId;
      if (runId) {
        selectRun(runId).catch(showError);
      }
    });

    elements.steps.addEventListener("click", (event) => {
      const item = event.target.closest(".list-item");
      if (!item || !elements.steps.contains(item)) {
        return;
      }
      const stepId = item.dataset.stepId;
      if (stepId) {
        selectStep(stepId).catch(showError);
      }
    });

    if (elements.liveGrid) {
      elements.liveGrid.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-action='toggle-stream']");
        if (!button) {
          return;
        }
        const card = button.closest(".live-card");
        if (card) {
          toggleLiveStream(card);
        }
      });
    }

    elements.tabButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const tabName = button.dataset.tab;
        if (tabName) {
          setTab(tabName);
        }
      });
    });

    elements.screenModeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const mode = button.dataset.screen;
        if (mode) {
          setScreenMode(mode);
        }
      });
    });

    elements.plan.addEventListener("change", setPlanControls);
  }

  function init() {
    setTab("decision");
    setPlanControls();
    setScreenMode("before");
    clearRunView();
    refreshAll({ selectNewest: true }).catch(showError);
    refreshDevices().catch(showError);
    bindEvents();
  }

  init();
})();
