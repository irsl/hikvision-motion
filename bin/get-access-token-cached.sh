#!/bin/bash

d="$(dirname $0)"
tokenpath=/tmp/token.json

if [ ! -f $tokenpath ] || test `find "$tokenpath" -mmin +30`; then
    # echo token either not exists, or too old
    "$d/get-access-token.sh" "/etc/creds.json" https://www.googleapis.com/auth/cloud-platform >$tokenpath
fi

cat "$tokenpath"

