// Synthetic data generation for showcase mode - a TS port of
// agents-python/app/synthetic.py. Every account, transaction and entity
// graph here is fabricated by a seeded RNG; nothing represents a real
// person or financial record. Kept independent from the Python version
// deliberately (same design, different language) rather than shared, since
// this runs in a completely separate deployment (Vercel) from the Python
// service.

const DUBLIN: [number, number] = [53.3498, -6.2603];
const LONDON: [number, number] = [51.5072, -0.1276];
const NEW_YORK: [number, number] = [40.7128, -74.006];
const SYDNEY: [number, number] = [-33.8688, 151.2093];
const CITIES: [number, number][] = [DUBLIN, LONDON, NEW_YORK, SYDNEY];

export const SYNTHETIC_SANCTIONS_LIST = new Set([
  "victor krantz holdings",
  "ashgrove trading fzco",
  "meridian bulk logistics",
]);

// Small deterministic PRNG (mulberry32) seeded from a string hash, so the
// same account_id always yields the same synthetic profile within a
// process - mirrors the Python side's per-key seeding without needing a
// crypto dependency for what is intentionally non-cryptographic randomness.
function hashSeed(key: string): number {
  let h = 1779033703 ^ key.length;
  for (let i = 0; i < key.length; i++) {
    h = Math.imul(h ^ key.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function rngFor(key: string): () => number {
  return mulberry32(hashSeed(key));
}

function randInt(rng: () => number, min: number, max: number): number {
  return Math.floor(rng() * (max - min + 1)) + min;
}

function choice<T>(rng: () => number, items: T[]): T {
  return items[randInt(rng, 0, items.length - 1)];
}

function gaussian(rng: () => number, mean: number, stddev: number): number {
  const u1 = Math.max(rng(), 1e-9);
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return mean + z * stddev;
}

export interface AccountProfile {
  accountId: string;
  homeCity: [number, number];
  typicalAmount: number;
  knownBeneficiaries: string[];
  knownDevices: string[];
}

export function accountProfile(accountId: string): AccountProfile {
  const rng = rngFor(accountId);
  const home = choice(rng, CITIES);
  const typical = Math.round(gaussian(rng, 110, 40) * 100) / 100;
  const beneficiaries = Array.from({ length: randInt(rng, 1, 4) }, () => `ben_${randInt(rng, 1000, 9999)}`);
  const devices = [`dev_${randInt(rng, 1000, 9999)}`];
  return {
    accountId,
    homeCity: home,
    typicalAmount: Math.max(20, typical),
    knownBeneficiaries: beneficiaries,
    knownDevices: devices,
  };
}

export function generateTransactionHistory(accountId: string, n = 12) {
  const profile = accountProfile(accountId);
  const rng = rngFor(accountId + ":history");
  const history = [];
  for (let i = 0; i < n; i++) {
    const amount = Math.max(1, Math.round(gaussian(rng, profile.typicalAmount, profile.typicalAmount * 0.25) * 100) / 100);
    history.push({
      id: `tx_hist_${accountId}_${i}`,
      amount,
      beneficiary_id: choice(rng, profile.knownBeneficiaries),
      device_id: profile.knownDevices[0],
    });
  }
  return history;
}

export function generateEntityGraph(accountId: string) {
  const rng = rngFor(accountId + ":graph");
  const linkedCount = randInt(rng, 0, 3);
  const linked = Array.from({ length: linkedCount }, () => `acct_${randInt(rng, 10000, 99999)}`);
  return { account_id: accountId, linked_accounts: linked, shared_device_count: linked.length };
}

export function checkSanctionsList(name: string) {
  const hit = SYNTHETIC_SANCTIONS_LIST.has(name.trim().toLowerCase());
  return { query: name, hit, list: "vaultwatch-synthetic-watchlist-v1" };
}

export function buildScoringContext(accountId: string, currentAmount: number, lastSeen?: Date) {
  const profile = accountProfile(accountId);
  const history = generateTransactionHistory(accountId, 12);
  const seenAt = lastSeen ?? new Date(Date.now() - 60 * 60 * 1000);
  return {
    recent_amounts: history.map((h) => h.amount),
    recent_count_last_hour: 1,
    recent_sum_last_hour: currentAmount,
    known_beneficiaries: profile.knownBeneficiaries,
    known_devices: profile.knownDevices,
    last_location: { lat: profile.homeCity[0], lon: profile.homeCity[1], timestamp: seenAt.toISOString() },
  };
}

export function generateDemoTransaction(forceRisky: boolean, accountIdIn?: string) {
  const rng = mulberry32((Date.now() ^ Math.floor(Math.random() * 1e9)) >>> 0);
  const accountId = accountIdIn ?? `acct_${randInt(rng, 10000, 99999)}`;
  const profile = accountProfile(accountId);
  const now = new Date();

  if (forceRisky) {
    const farCities = CITIES.filter((c) => c[0] !== profile.homeCity[0] || c[1] !== profile.homeCity[1]);
    const farCity = choice(rng, farCities.length ? farCities : [NEW_YORK]);
    return {
      id: `tx_${Math.random().toString(16).slice(2, 14)}`,
      account_id: accountId,
      amount: Math.round(profile.typicalAmount * (15 + rng() * 25) * 100) / 100,
      currency: "EUR",
      timestamp: now.toISOString(),
      lat: farCity[0],
      lon: farCity[1],
      beneficiary_id: `ben_${randInt(rng, 100000, 999999)}`,
      device_id: `dev_${randInt(rng, 100000, 999999)}`,
    };
  }

  return {
    id: `tx_${Math.random().toString(16).slice(2, 14)}`,
    account_id: accountId,
    amount: Math.max(1, Math.round(gaussian(rng, profile.typicalAmount, profile.typicalAmount * 0.2) * 100) / 100),
    currency: "EUR",
    timestamp: now.toISOString(),
    lat: profile.homeCity[0],
    lon: profile.homeCity[1],
    beneficiary_id: choice(rng, profile.knownBeneficiaries),
    device_id: profile.knownDevices[0],
  };
}
