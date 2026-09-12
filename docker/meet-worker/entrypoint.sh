#!/bin/bash
# Brings up the virtual display + virtual sound card that systemd's broll-xvfb/
# broll-pulseaudio units used to provide natively, then hands off to the RQ worker.
# Mirrors systemd/broll-xvfb.service + systemd/broll-pulseaudio.service, collapsed into
# one container since docker-compose runs one main process per service.
set -euo pipefail

export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 &

export XDG_RUNTIME_DIR=/tmp/pulse-runtime
mkdir -p "$XDG_RUNTIME_DIR"
pulseaudio --exit-idle-time=-1 --disallow-exit=1 --log-target=stderr &

# Give both daemons a moment to open their sockets before we depend on them.
sleep 2

pactl load-module module-null-sink sink_name=meet_sink sink_properties=device.description=MeetSink
pactl set-default-sink meet_sink
pactl set-default-source meet_sink.monitor

# exec so rq worker becomes PID 1 and receives docker stop's SIGTERM directly;
# Xvfb/pulseaudio are torn down with the rest of the container's process group on exit.
exec rq worker join-meeting --url "$REDIS_URL"
