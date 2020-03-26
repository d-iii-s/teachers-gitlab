#!/bin/sh

# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Charles University

# Try to determine where is this script located.
MY_HOME="$( which -- "$0" 2>/dev/null )"
[ -z "$MY_HOME" ] && MY_HOME="$( which -- "$BASH_SOURCE" 2>/dev/null )"
MY_HOME="$( dirname -- "$MY_HOME" )"
MY_HOME="$( cd "$MY_HOME" && echo "$PWD" )"

exec env \
    PYTHONPATH="$PYTHONPATH:$MY_HOME" \
    python -m matfyz.gitlab.teachers_gitlab "$@"
