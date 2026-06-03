# Packer Layout

This directory contains the cloud-image build templates used by `vidctl.py`.

## Build model

- One provider template per cloud
- Three role sources per template: `worker`, `client`, `coordinator`
- One manifest post-processor that writes `artifacts/image/manifest.json`

## Notes

- The templates are meant to produce cloud-native images, not local ISO files.
- `vidctl.py` can run a single role build for development, or build all roles for deployment.
