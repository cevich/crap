#!/bin/bash

set -e

UUID="$1"
FQIN="$2"
shift 2
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
        FULL_NAME=${NAME}_${UUID}
        # Don't create existing container
        docker inspect --type container -f '{{.Id}}' $FULL_NAME || \
            docker run --detach --name "$FULL_NAME" \
                --entrypoint=/bin/sh "$FQIN" \
                -c 'while sleep 10s; do :; done; exit'
        cat << EOF >> "$TEMPDIR/yaml.yml"

- inventory_hostname: $NAME
  ansible_host: $FULL_NAME
  ansible_connection: docker
  ansible_user: root
  ansible_ssh_user: root
  ansible_become: False
  docker_cid: $(docker inspect --type container -f '{{.Id}}' $FULL_NAME)
EOF
    done
) &> "$TEMPDIR/docker_output.log"

cat "$TEMPDIR/yaml.yml" > /dev/stdout
