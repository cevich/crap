#!/bin/bash

NAMES="$@"

(
    for NAME in $NAMES
    do
        docker rm -f "$NAME"
    done
) &> /dev/stderr
