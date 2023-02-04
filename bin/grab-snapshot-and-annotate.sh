#!/bin/bash

set -e

PICDIR=/data
dir="$(dirname $0)"
camurl="$1"
picname="$2"
if [ -z "$camurl" ]; then
  echo "Usage: $0 camurl [picname]"
  exit 1
fi

if [ -z "$picname" ]; then
  picname="$(mktemp -p /dev/shm)"
  trap "rm $picname*" EXIT
else
  picname="$PICDIR/$picname"
fi

timeout 3 ffmpeg -rtsp_transport tcp -i "$camurl" -vf "select=eq(pict_type\\,I)" -frames:v 1 "$picname" >/dev/null 2>&1
if [ -z "$DONT_ANNOTATE" ]; then
  "$dir/annotate.sh" "$picname"
fi
