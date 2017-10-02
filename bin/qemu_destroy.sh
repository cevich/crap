#!/bin/bash

MINARGS=1
CID="$1"

if [ "$#" -lt "$MINARGS" ]
then
    echo "Usage: $(basename $0) <CID>" > /dev/stderr
    echo
    exit 1
fi

(
    docker kill "$CID"
    sleep 1s
    docker rm -f "$CID"
) &> /dev/stderr
