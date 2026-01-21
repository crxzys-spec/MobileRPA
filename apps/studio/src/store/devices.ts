import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import type {
  Device,
  DeviceCommand,
  DeviceCommandRequest,
  DeviceSession,
} from "../api/types";
import { devicesService } from "../service/devices";
import { useAppStore } from "./app";

export const useDevicesStore = defineStore("devices", () => {
  const app = useAppStore();

  const devices = ref<Device[]>([]);
  const deviceSessions = ref<DeviceSession[]>([]);
  const deviceCommands = reactive<Record<string, DeviceCommand[]>>({});

  async function refreshDevices() {
    app.clearError();
    try {
      devices.value = await devicesService.listDevices();
      await refreshDeviceSessions();
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function refreshDeviceSessions() {
    app.clearError();
    try {
      deviceSessions.value = await devicesService.listDeviceSessions();
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function refreshDeviceCommands(deviceId: string, limit = 50) {
    app.clearError();
    try {
      deviceCommands[deviceId] = await devicesService.listDeviceCommands(
        deviceId,
        limit,
      );
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function sendDeviceCommand(
    deviceId: string,
    payload: DeviceCommandRequest,
  ) {
    app.clearError();
    try {
      const result = await devicesService.enqueueDeviceCommand(deviceId, payload);
      await refreshDeviceSessions();
      return result;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function clearDeviceQueue(deviceId: string) {
    app.clearError();
    try {
      const result = await devicesService.clearQueue(deviceId);
      await refreshDeviceSessions();
      return result;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  async function closeDeviceSession(deviceId: string) {
    app.clearError();
    try {
      const result = await devicesService.closeSession(deviceId);
      await refreshDeviceSessions();
      return result;
    } catch (error) {
      app.setError(error);
      throw error;
    }
  }

  return {
    devices,
    deviceSessions,
    deviceCommands,
    refreshDevices,
    refreshDeviceSessions,
    refreshDeviceCommands,
    sendDeviceCommand,
    clearDeviceQueue,
    closeDeviceSession,
  };
});
