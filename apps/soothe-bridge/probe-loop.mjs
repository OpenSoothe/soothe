/** One-off probe: dump raw loop_events frames for a loop (5s). */
import { Client } from "@mirasoth/soothe-client";

const url = process.argv[2] ?? "ws://127.0.0.1:8765";
const loopId = process.argv[3];
const ms = Number(process.argv[4] ?? 5000);

const c = new Client(url);
await c.connect();
await c.subscribe("loop_events", { loop_id: loopId }, 10_000);
const deadline = Date.now() + ms;
while (Date.now() < deadline) {
  const ev = await Promise.race([
    c.next(),
    new Promise((r) => setTimeout(() => r(undefined), deadline - Date.now())),
  ]);
  if (ev === undefined || ev === null) break;
  console.log(JSON.stringify(ev).slice(0, 600));
}
c.close();
process.exit(0);
