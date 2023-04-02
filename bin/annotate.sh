#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 image.jpg"
fi


dir="$(dirname $0)"
input_path="$1"
annotate_path="$input_path.annotate"
tags_path="$input_path.tags"

if [ -n "$SENTISIGHT_TOKEN" ]; then
    MODEL="Object-detection"
	set +x
	if curl -H "X-Auth-token: $SENTISIGHT_TOKEN" --data-binary @"$input_path" -H "Content-Type: application/octet-stream" -X POST "https://platform.sentisight.ai/api/pm-predict/$MODEL" | tee "$tags_path"; then
	   # it worked, no need to fall back
	   exit 0
	fi
	set -x
fi

# falling back to Google Vision AI

img="$(cat $input_path | base64 -w0)"
token="$($dir/get-access-token-cached.sh)"

cat <<EOF >$annotate_path
{
  "requests": [
    {
      "image": {
        "content": "$img"
      },
      "features": [
        {
          "maxResults": 10,
          "type": "OBJECT_LOCALIZATION"
        },
      ]
    }
  ]
}
EOF

trap "rm $annotate_path" EXIT

set +x
curl -X POST --silent \
    -H "Authorization: Bearer $token" \
    -H "x-goog-user-project: $GCP_PROJECT" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d @$annotate_path \
    "https://vision.googleapis.com/v1/images:annotate" | tee "$tags_path"
