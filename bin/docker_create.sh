#!/bin/bash

MINARGS=2

FQIN="$1"
NAME="$2"
EXTRA="$3"

TIMEOUT="5m"

set -e

if [ "$#" -lt "$MINARGS" ]
then
    echo "Usage: $(basename $0) <FQIN> <CONTAINER NAME> [extra...]" > /dev/stderr
    echo
    echo "Where the first two parameters are required, the third is optional."
    echo "The optional extra arguments are passed through to the docker run command."
    exit 1
fi

death() {
    (
    if [ -r "$TEMPDIR/docker_output.log" ]
    then
        cat "$TEMPDIR/docker_output.log" &> /dev/stderr
    fi
    rm -rf "$TEMPDIR"
    ) &> /dev/stderr
}

TEMPDIR=$(mktemp -d)
trap 'death' EXIT

(
    echo
    docker info
    echo
    docker pull "$FQIN"
    echo
    docker run --detach --name "$NAME" --cidfile="$TEMPDIR/$NAME" --entrypoint=/bin/sh $EXTRA "$FQIN" -c 'while sleep 10s; do :; done; exit'
) &> "$TEMPDIR/docker_output.log"

CID=$(timeout --foreground --signal=9 "$TIMEOUT" bash -c "while sleep 1s; do [ -r $TEMPDIR/$NAME ] && cat $TEMPDIR/$NAME && break; done")

cat << EOF > /dev/stdout
---
ansible_connection: docker
ansible_host: $NAME
ansible_user: root
ansible_ssh_user: root
ansible_become: False
docker_cid: $CID
EOF
