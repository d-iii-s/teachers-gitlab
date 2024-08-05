# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Charles University

"""
Helper GitLab functions.
"""

import base64
import http
import logging
import os
import pathlib
import subprocess
import time

import gitlab
import requests


def retries(
    n=None,
    interval=2,
    timeout=None,
    message="Operation timed-out (too many retries)"
):
    """
    To be used in for-loops to try action multiple times.
    Throws exception on time-out.
    """

    if (n is None) and (timeout is None):
        raise Exception("Specify either n or timeout for retries")

    if (n is not None) and (timeout is not None):
        interval = timeout / n

    if timeout is None:
        timeout = n * interval
    remaining = timeout
    n = 0
    while remaining > 0:
        remaining = remaining - interval
        n = n + 1
        yield n
        time.sleep(interval)
    raise Exception(message)


def retry_on_exception(message, exceptions):
    """
    Decorator for function that should be retried on some kind of exception.
    """

    def decorator(func):
        """
        Actual decorator (because we need to process arguments).
        """

        def wrapper(*args, **kwargs):
            """
            Wrapper calling the original function.
            """
            logger = logging.getLogger('retry_on_exception')
            last_ex = None
            for _ in retries(6, timeout=240):
                try:
                    return func(*args, **kwargs)
                except Exception as ex:
                    for allowed in exceptions:
                        if isinstance(ex, allowed):
                            last_ex = ex
                            if '%s' in message:
                                logger.warning(message, ex)
                            else:
                                logger.warning(message)
                            continue
                    if not last_ex:
                        raise ex
                    time.sleep(1)
            raise last_ex

        return wrapper

    return decorator


@retry_on_exception(
    'Failed to canonicalize a project, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def get_canonical_project(glb, project):
    """
    Ensure we have an instance of gitlab.*.Project.

    :param glb: GitLab instance.
    :param project: Either object already or path or project id.
    """

    if isinstance(project, (int, str)):
        return glb.projects.get(project)
    if isinstance(project, gitlab.v4.objects.Project):
        return project
    raise Exception("Unexpected object type.")

@retry_on_exception(
    'Failed to canonicalize a group, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def get_canonical_group(glb, group):
    """
    Ensure we have an instance of gitlab.*.Group.

    :param glb: GitLab instance.
    :param group: Either object already or path or group id.
    """

    if isinstance(group, (int, str)):
        return glb.groups.get(group)
    if isinstance(group, gitlab.v4.objects.Group):
        return group
    raise Exception("Unexpected object type.")

@retry_on_exception(
    'Failed to check group existence, will retry...',
    [gitlab.exceptions.GitlabGetError]
)
def is_existing_group(glb, group_path):
    try:
        _ = get_canonical_group(glb, group_path)
        return True
    except gitlab.exceptions.GitlabGetError as exp:
        if exp.response_code == http.HTTPStatus.NOT_FOUND:
            return False
        else:
            raise


def wait_for_project_to_be_forked(glb, project_path, timeout=None):
    """
    Wait until given project is not empty (forking complete).
    """

    project = get_canonical_project(glb, project_path)

    # In 10 minutes, even Torvalds' Linux repository is forked
    # on a not-that-fast instance :-)
    for _ in retries(360, 2, timeout):
        if not project.empty_repo:
            return
        # Force refresh (why project.refresh() does not work?)
        project = get_canonical_project(glb, project.path_with_namespace)


@retry_on_exception(
    'Failed to fork project, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def fork_project_idempotent(glb, parent, fork_namespace, fork_name):
    """
    Fork existing project or nothing if already forked.
    """

    parent = get_canonical_project(glb, parent)

    try:
        fork_handle = parent.forks.create({
            'namespace': fork_namespace,
            'path': fork_name,
            'name': fork_name,
        })
        fork_identity = fork_handle.id
    except gitlab.GitlabCreateError as exp:
        if exp.response_code == http.HTTPStatus.CONFLICT:
            fork_identity = "{}/{}".format(fork_namespace, fork_name)
        else:
            raise

    return get_canonical_project(glb, fork_identity)


def remove_fork_relationship(glb, project):
    """
    Remove the 'forked from' relationship of a project.
    """

    project = get_canonical_project(glb, project)
    try:
        project.delete_fork_relation()
    except gitlab.GitlabDeleteError as exp:
        if exp.response_code == http.HTTPStatus.NOT_MODIFIED:
            pass
        else:
            raise


@retry_on_exception(
    'Failed to create tag, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def create_tag(glb, project, tag_params):
    project = get_canonical_project(glb, project)
    project.tags.create(tag_params)


@retry_on_exception(
    'Failed to put file, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def put_file(glb, project, branch, file_path, file_contents, overwrite, commit_message):
    """
    Commit a file, overwriting existing content forcefully.
    """

    project = get_canonical_project(glb, project)
    commit_data = {
        'branch': branch,
        'commit_message': commit_message,
        'actions': [
            {
                'action': 'create',
                'file_path': file_path,
                'content': file_contents,
            },
        ],
    }
    try:
        return project.commits.create(commit_data)
    except gitlab.exceptions.GitlabCreateError as exp:
        if exp.response_code == http.HTTPStatus.BAD_REQUEST:
            if overwrite:
                commit_data['actions'][0]['action'] = 'update'
                return project.commits.create(commit_data)
            else:
                return None
        else:
            raise


@retry_on_exception(
    'Failed to get file, will retry...',
    [requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, gitlab.exceptions.GitlabHttpError]
)
def get_file_contents(glb, project, branch, file_path):
    """
    Retrieve current file contents on a GitLab repository.
    """

    project = get_canonical_project(glb, project)
    base_filename = os.path.basename(file_path)
    files = project.repository_tree(
        path=os.path.dirname(file_path),
        ref=branch,
        all=True,
        as_list=False
    )
    current_file = [f for f in files if f['name'] == base_filename]
    if not current_file:
        return None
    file_info = project.repository_blob(current_file[0]['id'])
    content = base64.b64decode(file_info['content'])
    return content


def get_timestamp(ts):
    """
    Try to convert any string to datetime with a timezone.
    """
    import dateparser

    result = dateparser.parse(ts)
    if not result:
        # Propagate parsing errors as exceptions.
        raise ValueError

    if not result.tzinfo:
        from datetime import datetime

        # Add local time zone if necessary.
        local_tz = datetime.now().astimezone().tzinfo
        return result.replace(tzinfo=local_tz)

    return result


def get_commit_with_tag(glb, project, tag_name):
    """
    Find a commit corresponding to a given tag in a project.
    Returns the commit object or 'None' if there is no such commit.
    """

    project = get_canonical_project(glb, project)

    tags = project.tags.list(iterator=True)
    if tag := next(filter(lambda t: t.name == tag_name, tags), None):
        return project.commits.get(tag.commit['id'])

    return None


def get_commit_before_deadline(
    glb, project, deadline, branch, commit_filter=lambda commit: True, tag=None
):
    """
    Get last commit just before the deadline but prefer a tag if available.
    """
    project = get_canonical_project(glb, project)
    if tag:
        commit = get_commit_with_tag(glb, project, tag)
        if commit:
            ts = get_timestamp(commit.created_at)
            if ts <= deadline:
                return commit
            else:
                # Tag is after deadline, fallback to normal resolution
                pass

    # By default, commits are ordered in reverse chronological order, i.e.,
    # the most recent first. We therefore take the first matching commit.
    commits = project.commits.list(ref_name=branch, until=deadline.isoformat(), iterator=True)
    if commit := next(filter(commit_filter, commits), None):
        return commit

    raise gitlab.exceptions.GitlabGetError("No matching commit found.")


def clone_or_fetch(glb, project, local_path):
    """
    Clone or update (fetch) to a local repository.
    """
    if os.path.isdir(os.path.join(local_path, '.git')):
        rc = subprocess.call(['git', 'fetch'], cwd=local_path)
        if rc != 0:
            raise Exception("git fetch failed")
        return

    if os.path.isdir(local_path):
        if os.listdir(local_path):
            raise Exception("There is non-empty directory that is not Git!")

    pathlib.Path(local_path).mkdir(parents=True, exist_ok=True)

    project = get_canonical_project(glb, project)
    git_url = project.ssh_url_to_repo
    rc = subprocess.call(['git', 'clone', git_url, local_path])
    if rc != 0:
        raise Exception("git clone failed")


def reset_to_commit(local_path, commit):
    """
    Reset a local repository to a given commit.
    """
    rc = subprocess.call(['git', 'reset', '--hard', commit], cwd=local_path)
    if rc != 0:
        raise Exception("git reset failed")
