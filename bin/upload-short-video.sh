#!/bin/bash

set -ex

d="$(dirname $0)"
VIDDIR=/dev/shm
camurl="$1"
vidurl="$2"
if [ -z "$vidurl" ]; then
  echo "Usage: $0 camurl https://vidurl.mp4"
  exit 1
fi

vidpath="$(mktemp -p $VIDDIR)"
rm "$vidpath"
trap "rm $vidpath" EXIT
timeout 20 ffmpeg -rtsp_transport tcp -t 15 -i "$camurl" -c:v copy  -c:a copy -f mp4 "$vidpath" >/dev/null 2>&1

token=$($d/get-access-token-cached.sh)
set +x
curl --silent --upload-file - -H "Authorization: Bearer $token" "$vidurl" < $vidpath

