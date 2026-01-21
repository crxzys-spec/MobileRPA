import { mrpaApi } from "../api/mrpa";
import type {
  RunLogResponse,
  RunMeta,
  RunRequest,
  StepDetails,
} from "../api/types";

export const runsService = {
  listRuns(): Promise<RunMeta[]> {
    return mrpaApi.listRuns();
  },
  getRun(runId: string): Promise<RunMeta> {
    return mrpaApi.getRun(runId);
  },
  getStep(runId: string, stepId: string): Promise<StepDetails> {
    return mrpaApi.getStep(runId, stepId);
  },
  getRunLog(runId: string, limit = 200): Promise<RunLogResponse> {
    return mrpaApi.getRunLog(runId, limit);
  },
  startRun(payload: RunRequest): Promise<RunMeta> {
    return mrpaApi.startRun(payload);
  },
  stopRun(runId: string): Promise<{ id: string; status: string }> {
    return mrpaApi.stopRun(runId);
  },
};
