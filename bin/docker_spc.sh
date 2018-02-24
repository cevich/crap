#!/bin/bash

set -e

FQIN=$1
TEST=$2

FQIN="${FQIN:-docker.io/cevich/handy_centos:latest}"
TEST="${TEST:-./bin/unittest.sh}"

source "$(dirname $0)/ci_lib.sh"

SPC_ARGS="--interactive --rm --privileged --ipc=host --pid=host --net=host"
VOL_ARGS="-v $PWD:$PWD:z -v /run:/run -v /etc/localtime:/etc/localtime
          -v /var/log:/var/log -v /sys/fs/cgroup:/sys/fs/cgroup
          -v /var/run/docker.sock:/var/run/docker.sock
          -v $WORKSPACE:$WORKSPACE:z"
ENV_ARGS="-e INITURI=$PWD/ -e TIMEOUT=1 -e DEBUG=${DEBUG:-false}
          -e TRAVIS_BRANCH=$TRAVIS_BRANCH -e WORKSPACE=$WORKSPACE
          --workdir $PWD"

# Make sure latest is really the latest
set +x
docker pull $FQIN
CMD="docker run $SPC_ARGS $VOL_ARGS $ENV_ARGS $FQIN $PWD/bin/pile.py './bin/venv-cmd.sh' $TEST"
echo "+$CMD"
exec $CMD
