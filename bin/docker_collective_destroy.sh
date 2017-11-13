#!/bin/bash

UUID="$1"
shift
NAMES="$@"

(
    for NAME in $NAMES
    do
        # Don't fail the play if the removal command fails
        [ -n "$NAME" ] && [ -n "$UUID" ] && docker rm -f "${NAME}_${UUID}"
    done
) &> /dev/stderr
