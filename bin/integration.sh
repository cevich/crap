#!/bin/bash

set -e

echo "Verify playbook executes using the defaults"
ansible-playbook ./main.yml

echo "Verify repository is left clean and unmodified"
git status
test "$(git status --porcelain | wc -l)" -eq "0"
