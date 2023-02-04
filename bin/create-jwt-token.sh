#!/bin/bash

set -euo pipefail

base64var() {
    printf "$1" | base64stream
}

base64stream() {
    base64 | tr '/+' '_-' | tr -d '=\n'
}

key_json_file="$1"
scope="$2"
valid_for_sec="${3:-3600}"
private_key=$(jq -r .private_key $key_json_file)
sa_email=$(jq -r .client_email $key_json_file)

header='{"alg":"RS256","typ":"JWT"}'
claim=$(cat <<EOF | jq -c .
  {
    "iss": "$sa_email",
    "scope": "$scope",
    "aud": "https://www.googleapis.com/oauth2/v4/token",
    "exp": $(($(date +%s) + $valid_for_sec)),
    "iat": $(date +%s)
  }
EOF
)
request_body="$(base64var "$header").$(base64var "$claim")"
signature=$(openssl dgst -sha256 -sign <(echo "$private_key") <(printf "$request_body") | base64stream)

printf "$request_body.$signature"
