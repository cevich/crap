#!/bin/bash

MINARGS=2

IMAGEPATH="$1"
NAME="$2"

TIMEOUT="5m"

set -e

if [ "$#" -lt "$MINARGS" ]
then
    echo "Usage: $(basename $0) <FQIN> <CONTAINER NAME> [extra...]" > /dev/stderr
    echo
    echo "Where the first two parameters are required, the third is optional."
    echo "The optional extra arguments are used by ansible to connect to the docker daemon."
    exit 1
fi

death() {
    if [ -r "$TEMPDIR/docker_output.log" ]
    then
        cat "$TEMPDIR/docker_output.log"
    fi
    rm -rf "$TEMPDIR"
}

TEMPDIR=$(mktemp -d)
trap 'rm -rf "$TEMPDIR"' EXIT

echo "$TEMPDIR"

(
    echo
    docker info
    echo
    docker pull "$FQIN"
    echo
    docker run --detach --name "$NAME" --cidfile="$TEMPDIR/$NAME" --entrypoint=/bin/sh "$FQIN" -c 'while sleep 60s; do :; done;'
) &> /dev/stderr

CID=$(timeout --foreground --signal=9 "$TIMEOUT" bash -c "while sleep 1s; do [ -r $TEMPDIR/$NAME ] && cat $TEMPDIR/$NAME && break; done")

cat << EOF > /dev/stdout
---
ansible_connection: docker
ansible_host: $NAME
ansible_user: root
ansible_ssh_user: root
ansible_become: False
ansible_docker_extra_args: $EXTRA
crap_cid: $CID
EOF
