#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 image.jpg"
fi


dir="$(dirname $0)"
input_path="$1"
img="$(cat $input_path | base64 -w0)"
annotate_path="$input_path.annotate"
tags_path="$input_path.tags"
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
