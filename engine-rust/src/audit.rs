use crate::models::{AuditEntry, VerifyResponse};
use chrono::Utc;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::Mutex;

const GENESIS_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// A hash-chained, append-only audit log. Every entry's hash covers its own
/// fields *and* the previous entry's hash, so mutating or deleting any past
/// entry (or reordering them) breaks the chain from that point forward.
/// `verify()` walks the whole chain and reports the first broken link, which
/// is what an auditor or a Central-Bank-style examiner actually wants: not
/// just "something is wrong" but "here is exactly where trust ends".
pub struct AuditLog {
    path: PathBuf,
    entries: Mutex<Vec<AuditEntry>>,
}

fn compute_hash(
    seq: u64,
    timestamp: &chrono::DateTime<Utc>,
    event_type: &str,
    subject_id: &str,
    payload: &Value,
    prev_hash: &str,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(prev_hash.as_bytes());
    hasher.update(seq.to_be_bytes());
    hasher.update(timestamp.to_rfc3339().as_bytes());
    hasher.update(event_type.as_bytes());
    hasher.update(subject_id.as_bytes());
    hasher.update(payload.to_string().as_bytes());
    hex::encode(hasher.finalize())
}

impl AuditLog {
    pub fn open(path: PathBuf) -> std::io::Result<Self> {
        let entries = if path.exists() {
            let file = File::open(&path)?;
            BufReader::new(file)
                .lines()
                .map_while(Result::ok)
                .filter(|line| !line.trim().is_empty())
                .map(|line| serde_json::from_str::<AuditEntry>(&line))
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?
        } else {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            Vec::new()
        };

        Ok(Self {
            path,
            entries: Mutex::new(entries),
        })
    }

    pub fn append(
        &self,
        event_type: String,
        subject_id: String,
        payload: Value,
    ) -> std::io::Result<AuditEntry> {
        let mut entries = self.entries.lock().expect("audit log mutex poisoned");
        let seq = entries.len() as u64 + 1;
        let prev_hash = entries
            .last()
            .map(|e| e.hash.clone())
            .unwrap_or_else(|| GENESIS_HASH.to_string());
        let timestamp = Utc::now();
        let hash = compute_hash(
            seq,
            &timestamp,
            &event_type,
            &subject_id,
            &payload,
            &prev_hash,
        );

        let entry = AuditEntry {
            seq,
            timestamp,
            event_type,
            subject_id,
            payload,
            prev_hash,
            hash,
        };

        self.persist(&entry)?;
        entries.push(entry.clone());
        Ok(entry)
    }

    fn persist(&self, entry: &AuditEntry) -> std::io::Result<()> {
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        writeln!(file, "{}", serde_json::to_string(entry)?)?;
        file.sync_data()
    }

    pub fn verify(&self) -> VerifyResponse {
        let entries = self.entries.lock().expect("audit log mutex poisoned");
        // Read the persisted log, not just the in-memory copy. Hold the append
        // lock so verification cannot observe a half-written line.
        let disk: std::io::Result<Vec<AuditEntry>> = (|| {
            if !self.path.exists() && entries.is_empty() {
                return Ok(Vec::new());
            }
            BufReader::new(File::open(&self.path)?)
                .lines()
                .map(|line| {
                    serde_json::from_str(&line?)
                        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
                })
                .collect()
        })();
        let disk = match disk {
            Ok(disk) => disk,
            Err(_) => {
                return VerifyResponse {
                    valid: false,
                    entries_checked: 0,
                    first_broken_seq: Some(1),
                }
            }
        };
        if disk.len() != entries.len() {
            return VerifyResponse {
                valid: false,
                entries_checked: disk.len() as u64,
                first_broken_seq: Some(disk.len().min(entries.len()) as u64 + 1),
            };
        }
        let mut expected_prev = GENESIS_HASH.to_string();

        for (index, entry) in disk.iter().enumerate() {
            let recomputed = compute_hash(
                entry.seq,
                &entry.timestamp,
                &entry.event_type,
                &entry.subject_id,
                &entry.payload,
                &entry.prev_hash,
            );

            if entry.seq != index as u64 + 1
                || entry.prev_hash != expected_prev
                || recomputed != entry.hash
                || entry.hash != entries[index].hash
            {
                return VerifyResponse {
                    valid: false,
                    entries_checked: entry.seq,
                    first_broken_seq: Some(entry.seq),
                };
            }
            expected_prev = entry.hash.clone();
        }

        VerifyResponse {
            valid: true,
            entries_checked: entries.len() as u64,
            first_broken_seq: None,
        }
    }

    pub fn recent(&self, limit: usize) -> Vec<AuditEntry> {
        let entries = self.entries.lock().expect("audit log mutex poisoned");
        entries.iter().rev().take(limit).cloned().collect()
    }

    /// Test-only: corrupts the payload of an existing entry in place, without
    /// recomputing its hash, so `verify()` can be exercised against real
    /// tampering. Compiled only under `cfg(test)` - there is no runtime path
    /// that can reach this in a running service.
    #[cfg(test)]
    pub fn corrupt_for_test(&self, seq: u64, new_payload: Value) {
        let mut entries = self.entries.lock().unwrap();
        if let Some(entry) = entries.iter_mut().find(|e| e.seq == seq) {
            entry.payload = new_payload;
            let mut file = File::create(&self.path).unwrap();
            for entry in entries.iter() {
                writeln!(file, "{}", serde_json::to_string(entry).unwrap()).unwrap();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn temp_log() -> AuditLog {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("audit.log");
        std::mem::forget(dir); // keep the tempdir alive for the test's lifetime
        AuditLog::open(path).unwrap()
    }

    #[test]
    fn empty_log_is_valid() {
        let log = temp_log();
        let result = log.verify();
        assert!(result.valid);
        assert_eq!(result.entries_checked, 0);
    }

    #[test]
    fn chain_of_appends_verifies() {
        let log = temp_log();
        log.append("case.opened".into(), "case_1".into(), json!({"risk": 10}))
            .unwrap();
        log.append(
            "case.escalated".into(),
            "case_1".into(),
            json!({"risk": 80}),
        )
        .unwrap();
        log.append(
            "case.closed".into(),
            "case_1".into(),
            json!({"outcome": "confirmed_fraud"}),
        )
        .unwrap();

        let result = log.verify();
        assert!(result.valid);
        assert_eq!(result.entries_checked, 3);
        assert_eq!(result.first_broken_seq, None);
    }

    #[test]
    fn tampering_with_an_entry_breaks_the_chain_from_that_point() {
        let log = temp_log();
        log.append("case.opened".into(), "case_1".into(), json!({"risk": 10}))
            .unwrap();
        log.append(
            "case.escalated".into(),
            "case_1".into(),
            json!({"risk": 80}),
        )
        .unwrap();
        log.append(
            "case.closed".into(),
            "case_1".into(),
            json!({"outcome": "confirmed_fraud"}),
        )
        .unwrap();

        // Tamper with entry 2 without recomputing its hash - simulates
        // someone editing the log file directly.
        log.corrupt_for_test(2, json!({"risk": 0}));

        let result = log.verify();
        assert!(!result.valid);
        assert_eq!(result.first_broken_seq, Some(2));
    }

    #[test]
    fn reloading_from_disk_preserves_the_chain() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("audit.log");

        {
            let log = AuditLog::open(path.clone()).unwrap();
            log.append("case.opened".into(), "case_1".into(), json!({"risk": 10}))
                .unwrap();
            log.append(
                "case.escalated".into(),
                "case_1".into(),
                json!({"risk": 80}),
            )
            .unwrap();
        }

        let reloaded = AuditLog::open(path).unwrap();
        let result = reloaded.verify();
        assert!(result.valid);
        assert_eq!(result.entries_checked, 2);
    }
    #[test]
    fn write_failure_is_reported_without_advancing_chain() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("audit.log");
        let log = AuditLog::open(path.clone()).unwrap();
        std::fs::create_dir(&path).unwrap();
        assert!(log
            .append("case.opened".into(), "tx_1".into(), json!({}))
            .is_err());
        assert!(log.recent(10).is_empty());
    }

    #[test]
    fn external_disk_tampering_is_detected() {
        let log = temp_log();
        log.append("case.opened".into(), "tx_1".into(), json!({"amount": 10}))
            .unwrap();
        let original = std::fs::read_to_string(&log.path).unwrap();
        std::fs::write(
            &log.path,
            original.replace("\"amount\":10", "\"amount\":99"),
        )
        .unwrap();
        assert!(!log.verify().valid);
    }
}
