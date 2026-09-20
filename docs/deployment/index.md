---
title: Deployment
description: Deploy Nira in production environments
---

# Deployment

Nira supports multiple deployment strategies for different environments
and scales.

## Docker

The recommended way to deploy Nira in production. Multi-stage builds
with CPU and GPU (NVIDIA CUDA, AMD ROCm) variants.

[:octicons-arrow-right-24: Docker deployment](docker.md)

## systemd (Linux)

Run Nira as a managed system service on Linux servers.

[:octicons-arrow-right-24: systemd setup](systemd.md)

## launchd (macOS)

Register Nira as a launch agent on macOS.

[:octicons-arrow-right-24: launchd setup](launchd.md)

## API Server

Run Nira as an OpenAI-compatible HTTP server via `nira serve`.

[:octicons-arrow-right-24: API server guide](api-server.md)
