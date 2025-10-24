#!/bin/bash

set -uoe pipefail

get_latest_commit() {
    git -C "$1" log --format='%H %ct' --max-count=1
}

git_clone() {
    git clone --depth=1 "$1" "$2"
}

my_temp="$( mktemp -d )"
trap "rm -rf \"$my_temp\"" EXIT

cd "$my_temp"

git_clone https://gitlab.mff.cuni.cz/teaching/utils/teachers-gitlab.git mff
git_clone https://github.com/d-iii-s/teachers-gitlab.git github

read -r commit_mff timestamp_mff <<<"$( get_latest_commit mff )"
read -r commit_github timestamp_github <<<"$( get_latest_commit github )"

if [ "$commit_mff" = "$commit_github" ]; then
    (
        echo
        echo 'Everything is okay, Git mirrors are synchronized :-)'
        echo
    ) >&2
    exit 0
fi

(
    echo
    echo "==========================================================="
    echo
    echo "FATAL: Different commits found on MFF GitLab and on GitHub!"
    echo
    echo "Latest commit on MFF GitLab is $commit_mff."
    echo "Latest commit on GitHub is $commit_github."
    echo
    if [ "$timestamp_mff" -lt "$timestamp_github" ]; then
        echo "It seems that MFF GitLab is behind GitHub."
    else
        echo "It seems that GitHub is behind MFF GitLab."
    fi
) >&2

exit 1
