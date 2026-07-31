# python base (not bare ubuntu): modal's image builder runs `python -m pip
# install` inside every image, so a `python` executable must be present. Harbor's
# own hello-world is FROM ubuntu:24.04 and therefore RemoteErrors on modal, which
# is why we ship this modal-compatible equivalent instead of running theirs.
FROM python:3.12-slim

WORKDIR /app
