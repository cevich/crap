#!/bin/bash

set -e

echo "Running Python Unittests"
(cd ./tests && python3 -m unittest --failfast --buffer --verbose)
