import { mrpaApi } from "../api/mrpa";
import type {
  Device,
  DeviceCommand,
  DeviceCommandRequest,
  DeviceQueueClearResponse,
  DeviceSession,
  DeviceSessionCloseResponse,
} from "../api/types";

export const devicesService = {
  listDevices(): Promise<Device[]> {
    return mrpaApi.listDevices();
  },
  listDeviceSessions(): Promise<DeviceSession[]> {
    return mrpaApi.listDeviceSessions();
  },
  listDeviceCommands(
    deviceId: string,
    limit = 50,
  ): Promise<DeviceCommand[]> {
    return mrpaApi.listDeviceCommands(deviceId, limit);
  },
  enqueueDeviceCommand(
    deviceId: string,
    payload: DeviceCommandRequest,
  ): Promise<DeviceCommand> {
    return mrpaApi.enqueueDeviceCommand(deviceId, payload);
  },
  clearQueue(deviceId: string): Promise<DeviceQueueClearResponse> {
    return mrpaApi.clearDeviceQueue(deviceId);
  },
  closeSession(deviceId: string): Promise<DeviceSessionCloseResponse> {
    return mrpaApi.closeDeviceSession(deviceId);
  },
};
