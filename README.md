# Teachers GitLab for mass actions on GitLab

Utilities to help you manage multiple repositories at once.
Targets teachers that need to manage separate repository for each
student and massively fork, clone or upload files to them.

## Installation

It is possible to install the script via:

```shell
pip install -r requirements.txt
./setup.py build
./setup.py install
```

This will give you `teachers_gitlab` on your `$PATH`. You can also
use `virtualenv` to test locally or use the provided shell script
wrapper (as used in the examples).

## Configuration

The script expects a configuration file for Python GitLab
format (`config.ini` in the following examples):

```ini
[global]
default = mff
ssl_verify = true
timeout = 5

[mff]
url = https://gitlab.mff.cuni.cz/
private_token = your-private-token
```

Generally, the script expects that the user has a CSV file with
list of students on which to operate.

For the following examples, we will assume CSV `students.csv` with
the following contents:

```csv
email,login,number
student1@mff.cuni.cz,student1,1
student2@mff.cuni.cz,student2,2
```

## `fork`

Fork repository for all users given in a CSV file.

```shell
./teachers_gitlab.sh fork \
    --config-file config.ini \
    --users students.csv \
    --from teaching/course/upstream/template \
    --to "teaching/course/student-{number}-{login}" \
    --hide-fork
```

will fork the `teaching/course/upstream/template` into
repositories `teaching/course/student-1-student1`
and `teaching/course/student-2-student2`, removing the
fork relationship.

## `unprotect`

Remove branch protection, typically needed for `master` branch
in simple setups.

Assuming the same input files as in `fork`, following command
unprotects `master` branch for all repositories from the previous
step.

```shell
./teachers_gitlab.sh unprotect \
    --config-file config.ini \
    --users students.csv \
    --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
    --branch master
```

## `add-member`

Add member to a project. Typically called after `fork` (see above).

Adding users to their repositories from the example above is done with

```shell
./teachers_gitlab.sh add-member \
    --config-file config.ini \
    --users students.csv \
    --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
    --access-level devel
```

## `clone`

Clone project to local disk. It is possible to specify a deadline to
checkout to a specific commit (last before given deadline).

```shell
./teachers_gitlab.sh clone \
    --config-file config.ini \
    --users students.csv \
    --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
    --to "solutions/01-{number}-{login}" \
    --deadline '2020-01-01T00:00:00Z'
```

## `deadline-commit`

Get last commits before a given deadline.

By default, it generates a CSV with logins and commit ids.

```shell
./teachers_gitlab.sh deadline-commit \
    --config-file config.ini \
    --users students.csv \
    --project "teaching/nswi177/2020-summer/solution-{number}-{login}" \
    --deadline '2020-01-01T00:00:00Z' \
    --output commits_01.csv \
    --first-line 'login,number,commit' \
    --format '{login},{number},{commit.id}'
```
