// In-process, hash-chained audit log for showcase mode - same design as
// engine-rust's audit.rs (SHA-256 chain over prev_hash + fields), reimplemented
// with the Web Crypto API so it runs in a serverless function with no native
// dependency. Held in module-level memory: on Vercel that means it persists
// for the lifetime of a warm serverless instance and is lost on cold start
// or when a request lands on a different instance - fine for a live demo of
// the *mechanism*, not a substitute for engine-rust's durable file-backed
// chain, which is what docker-compose / full mode actually runs.

const GENESIS_HASH = "0".repeat(70);

export interface AuditEntry {
  seq: number;
  timestamp: string;
  event_type: string;
  subject_id: string;
  payload: unknown;
  prev_hash: string;
  hash: string;
}

const entries: AuditEntry[] = [];

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function computeHash(
  seq: number,
  timestamp: string,
  eventType: string,
  subjectId: string,
  payload: unknown,
  prevHash: string,
): Promise<string> {
  const material = `${prevHash}|${seq}|${timestamp}|${eventType}|${subjectId}|${JSON.stringify(payload)}`;
  return sha256Hex(material);
}

export async function appendAuditEntry(eventType: string, subjectId: string, payload: unknown): Promise<AuditEntry> {
  const seq = entries.length + 1;
  const prevHash = entries.length ? entries[entries.length - 1].hash : GENESIS_HASH;
  const timestamp = new Date().toISOString();
  const hash = await computeHash(seq, timestamp, eventType, subjectId, payload, prevHash);

  const entry: AuditEntry = { seq, timestamp, event_type: eventType, subject_id: subjectId, payload, prev_hash: prevHash, hash };
  entries.push(entry);
  return entry;
}

export interface VerifyResult {
  valid: boolean;
  entries_checked: number;
  first_broken_seq: number | null;
}

export async function verifyAuditChain(): Promise<VerifyResult> {
  let expectedPrev = GENESIS_HASH;
  for (const entry of entries) {
    const recomputed = await computeHash(
      entry.seq,
      entry.timestamp,
      entry.event_type,
      entry.subject_id,
      entry.payload,
      entry.prev_hash,
    );
    if (entry.prev_hash !== expectedPrev || recomputed !== entry.hash) {
      return { valid: false, entries_checked: entry.seq, first_broken_seq: entry.seq };
    }
    expectedPrev = entry.hash;
  }
  return { valid: true, entries_checked: entries.length, first_broken_seq: null };
}

export function recentAuditEntries(limit = 20): AuditEntry[] {
  return entries.slice(-limit).reverse();
}
