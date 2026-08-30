# Manga to Video Pipeline Core

Comic/Manga to Video Tool (v5, FINAL architecture).

## Overview
- Local-first AI batch preprocessing (Layout -> OCR -> Script -> TTS)
- Immutable staged artifacts with 2-tier ID system (AI hash IDs + Persistent Anchors)
- Deterministic Render Plan -> FFmpeg Renderer & CapCut Project Exporter

## Architecture Reference
See [architecture.md](architecture.md) for full architectural specification.
