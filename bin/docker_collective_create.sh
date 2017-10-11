#!/bin/bash

set -e

FQIN="registry.fedoraproject.org/fedora:latest"
NAMES="$@"

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
    echo -e '---\n' > "$TEMPDIR/yaml.yml"
    echo
    for NAME in $NAMES
    do
        docker inspect --type container -f '{{.Id}}' $NAME || \
            docker run --detach --name "$NAME" --entrypoint=/bin/sh "$FQIN" -c 'while sleep 10s; do :; done; exit'
        cat << EOF >> "$TEMPDIR/yaml.yml"

$NAME:
    ansible_connection: docker
    ansible_host: $NAME
    ansible_user: root
    ansible_ssh_user: root
    ansible_become: False
    docker_cid: $(docker inspect --type container -f '{{.Id}}' $NAME)
EOF
    done
) &> "$TEMPDIR/docker_output.log"

cat "$TEMPDIR/yaml.yml" > /dev/stdout
