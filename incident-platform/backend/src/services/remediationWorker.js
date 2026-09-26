import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { ApiError } from "../middleware/errors.js";
const reasoner = fileURLToPath(new URL("../../../../llm-reasoner/", import.meta.url));
export function remediationWorker(payload, onProgress) {
  return new Promise((resolve, reject) => {
    let pending = "", result, failed = false;
    let processing = Promise.resolve();
    const uncertain = () => {
      failed = true;
      reject(new ApiError(502, "REMEDIATION_UNCERTAIN", "Worker failed or timed out. Do not retry execution; inspect the demo manually."));
    };
    const child = execFile(`${reasoner}.venv/bin/python`, ["-m", "llm_reasoner.demo_remediation"], {
      cwd: reasoner, timeout: 240000, maxBuffer: 262144,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, PYTHONDONTWRITEBYTECODE: "1" },
    }, async error => {
      await processing;
      if (failed) return;
      if (error || pending.trim() || !result?.proposal || !result?.action || !Array.isArray(result?.history)) return uncertain();
      resolve(result);
    });
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", chunk => {
      pending += chunk;
      let end;
      while ((end = pending.indexOf("\n")) !== -1) {
        const line = pending.slice(0, end); pending = pending.slice(end + 1);
        processing = processing.then(async () => {
          if (failed) return;
          const message = JSON.parse(line);
          if (message.event) {
            if (result || payload.operation !== "execute" || message.event !== "VERIFYING" || !onProgress) throw new Error();
            await onProgress(message);
            // Python waits for this durable acknowledgement before health I/O.
            child.stdin.write("VERIFICATION_PERSISTED\n");
          } else {
            if (result) throw new Error();
            result = message;
          }
        }).catch(() => { uncertain(); child.kill(); });
      }
    });
    child.stdin.on("error", () => { uncertain(); child.kill(); });
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  });
}
