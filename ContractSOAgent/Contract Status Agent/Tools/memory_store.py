# Tool Name   : Contract Status Memory Store
# Skill       : Contract Status Agent
# Version     : 1.0.0
# Last Updated: 2026-04-30
# Description : Reads and writes Contract Status Agent memory from local disk by
#               default, or from Google Cloud Storage when GCS_MEMORY_BUCKET is set.
# Dependencies: google-cloud-storage
# ENV Vars    : GCS_MEMORY_BUCKET, GCS_MEMORY_BLOB

import json
import os
from pathlib import Path


SKILL_NAME = "Contract Status Agent"
DEFAULT_MEMORY = {
    "skill": SKILL_NAME,
    "last_run": None,
    "last_action": None,
    "state": {
        "last_processed_id": None,
        "pending_items": [],
        "completed_items": [],
        "status_snapshot": {},
        "run_history": [],
    },
    "known_issues": [],
}


class MemoryStore:
    def __init__(self, local_path):
        self.local_path = Path(local_path)
        self.bucket_name = os.getenv("GCS_MEMORY_BUCKET", "").strip()
        self.blob_name = os.getenv("GCS_MEMORY_BLOB", "contract-status-agent/memory.json").strip()
        self._client = None

    @property
    def using_gcs(self):
        return bool(self.bucket_name)

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def _default_memory(self):
        return json.loads(json.dumps(DEFAULT_MEMORY))

    def read(self):
        if self.using_gcs:
            return self._read_gcs()
        return self._read_local()

    def write(self, memory):
        if self.using_gcs:
            self._write_gcs(memory)
        else:
            self._write_local(memory)

    def _read_local(self):
        if self.local_path.exists():
            return json.loads(self.local_path.read_text(encoding="utf-8"))
        return self._default_memory()

    def _write_local(self, memory):
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(memory, indent=2), encoding="utf-8")

    def _read_gcs(self):
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(self.blob_name)
        if not blob.exists():
            return self._default_memory()
        return json.loads(blob.download_as_text(encoding="utf-8"))

    def _write_gcs(self, memory):
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        blob = bucket.blob(self.blob_name)
        blob.upload_from_string(
            json.dumps(memory, indent=2),
            content_type="application/json",
        )
