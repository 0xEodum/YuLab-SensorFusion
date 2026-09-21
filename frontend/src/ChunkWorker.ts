import type { WorldSpec } from "@yulab/contracts";
import { abortError, type ChunkGenerator } from "@yulab/world";

/** Single bounded worker, one transferred result at a time. Termination cancels
 * synchronous meshing immediately; a replacement worker receives the same snapshot. */
export class ChunkWorker {
  private worker: Worker | null = null;
  private id = 0;
  private pending: (() => void) | null = null;
  private disposed = false;
  readonly stats = { starts: 0, cancellations: 0, completed: 0 };
  constructor(private spec: WorldSpec) {}
  generate: ChunkGenerator = (coord, pitch, signal) => {
    if (this.disposed) return Promise.reject(new Error("Worker disposed"));
    if (signal.aborted) return Promise.reject(abortError());
    if (this.pending) return Promise.reject(new Error("Worker already busy"));
    const initialize = !this.worker;
    if (!this.worker) {
      this.worker = new Worker(new URL("./chunk.worker.ts", import.meta.url), {
        type: "module",
      });
      this.stats.starts++;
    }
    const worker = this.worker,
      id = ++this.id;
    return new Promise((resolve, reject) => {
      const finish = () => {
        clearTimeout(timeout);
        signal.removeEventListener("abort", cancel);
        worker.onmessage = null;
        worker.onerror = null;
        worker.onmessageerror = null;
        this.pending = null;
      };
      const fail = (error: Error) => {
        finish();
        worker.terminate();
        this.worker = null;
        reject(error);
      };
      const cancel = () => {
        this.stats.cancellations++;
        fail(abortError());
      };
      const timeout = setTimeout(
        () => fail(new Error("Chunk worker timed out after 30 seconds")),
        30_000,
      );
      this.pending = cancel;
      signal.addEventListener("abort", cancel, { once: true });
      worker.onerror = (event) => {
        event.preventDefault();
        fail(new Error(event.message || "Chunk worker failed"));
      };
      worker.onmessageerror = () => fail(new Error("Invalid worker message"));
      worker.onmessage = (event) => {
        if (event.data.id !== id) return;
        if (event.data.error) {
          fail(new Error(event.data.error));
          return;
        }
        finish();
        this.stats.completed++;
        resolve(event.data.data);
      };
      worker.postMessage({
        id,
        coord,
        pitch,
        ...(initialize ? { spec: this.spec } : {}),
      });
    });
  };
  dispose() {
    this.disposed = true;
    this.pending?.();
    this.worker?.terminate();
    this.worker = null;
  }
}
