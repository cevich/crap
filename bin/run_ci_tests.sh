#!/bin/bash

set -e

DISTRO="${DISTRO:-centos}"
TEST="${TEST:-./bin/typos.sh}"

source "$(dirname $0)/ci_lib.sh"
TOP_WORKSPACE=$WORKSPACE

docker pull docker.io/cevich/handy_${DISTRO}:latest
for DISTRO in centos fedora ubuntu
do
    export WORKSPACE="$TOP_WORKSPACE/$DISTRO"
    mkdir -p "$WORKSPACE"
    echo ""
    echo "Testing with $TEST on $DISTRO"
    bin/docker_spc.sh docker.io/cevich/handy_${DISTRO}:latest ${TEST}
    [ "$?" -eq "0" ] || break
done
