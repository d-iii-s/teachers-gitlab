#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Charles University

import argparse
import csv
import collections
import json
import locale
import sys
import http
import os
import pathlib
import re
import time
import gitlab
import matfyz.gitlab.utils as mg

_registered_commands = []

def register_command(name):
    def decorator(func):
        _registered_commands.append({
            'name': name,
            'func': func
        })
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def get_registered_commands():
    return _registered_commands[:]

class Parameter:
    """
    Base class for parameter annotation.
    """
    def __init__(self):
        pass

    def register(self, argument_name, subparser):
        pass

    def get_value(self, argument_name, glb, parsed_options):
        pass

class UserListParameter(Parameter):
    """
    Parameter annotation to mark list of users.
    """
    def __init__(self, has_to_be_gitlab_users=True):
        Parameter.__init__(self)
        self.return_as_gitlab_users = has_to_be_gitlab_users

    def register(self, argument_name, subparser):
        subparser.add_argument(
            '--users',
            required=True,
            dest='csv_users',
            metavar='LIST.csv',
            help='CSV with users.'
        )
        subparser.add_argument(
            '--login-column',
            dest='csv_users_login_column',
            default='login',
            metavar='COLUMN_NAME',
            help='Column name with login information'
        )

    def get_value(self, argument_name, glb, parsed_options):
        users = []
        with open(parsed_options.csv_users) as inp:
            data = csv.DictReader(inp)
            for user in data:
                user_login = user.get(parsed_options.csv_users_login_column)
                matching_users = glb.users.list(username=user_login)
                if len(matching_users) == 0:
                    if self.return_as_gitlab_users:
                        print("WARNING: user {} not found!".format(user_login), file=sys.stderr)
                        continue
                    else:
                        class UserMock:
                            def __init__(self, name):
                                self.username = name
                        user_obj = UserMock(user_login)
                else:
                    user_obj = matching_users[0]
                user_obj.row = user
                yield user_obj


class DryRunParameter(Parameter):
    """
    Parameter annotation to mark switch for dry run.
    """
    def __init__(self):
        Parameter.__init__(self)

    def register(self, argument_name, subparser):
        subparser.add_argument(
            '--dry-run',
            dest='dry_run',
            default=False,
            action='store_true',
            help='Simulate but do not make any real changes.'
        )

    def get_value(self, argument_name, glb, parsed_options):
        return parsed_options.dry_run

class ActionParameter(Parameter):
    """
    Parameter annotation to create corresponding CLI option.
    """
    def __init__(self, name, **kwargs):
        Parameter.__init__(self)
        self.name = name
        self.extra_args = kwargs

    def register(self, argument_name, subparser):
        subparser.add_argument(
            '--' + self.name,
            dest='arg_' + argument_name,
            **self.extra_args
        )

    def get_value(self, argument_name, glb, parsed_options):
        return getattr(parsed_options, 'arg_' + argument_name)

class CommandParser:
    def __init__(self):
        self.args_common = argparse.ArgumentParser(add_help=False)
        self.args_common.add_argument(
            '--debug',
            default=False,
            dest='debug',
            action='store_true',
            help='Print debugging messages.'
        )
        self.args_common.add_argument(
            '--config-file',
            default=None,
            action='append',
            dest='gitlab_config_file',
            help='GitLab configuration file.'
        )
        self.args_common.add_argument(
            '--instance',
            default=None,
            dest='gitlab_instance',
            help='Which GitLab instance to choose.'
        )

        self.args = argparse.ArgumentParser(
            description='Teachers GitLab for mass actions on GitLab'
        )

        self.args.set_defaults(func=None)
        self.args_sub = self.args.add_subparsers(help='Select what to do')

        args_help = self.args_sub.add_parser('help', help='Show this help.')
        args_help.set_defaults(func=None)

        self.parsed_options = None

    def add_command(self, name, callback_func):
        short_help = callback_func.__doc__
        if short_help is not None:
            short_help = short_help.strip().split("\n")[0]
        parser = self.args_sub.add_parser(
            name,
            help=short_help,
            parents=[self.args_common]
        )
        for dest, param in callback_func.__annotations__.items():
            param.register(dest, parser)

        def callback_wrapper(glb, cfg, callback):
            kwargs = {}
            for dest, param in callback.__annotations__.items():
                kwargs[dest] = param.get_value(dest, glb, cfg)
            callback(glb, **kwargs)

        parser.set_defaults(func=lambda glb, cfg: callback_wrapper(glb, cfg, callback_func))

    def parse_args(self, argv):
        if len(argv) < 1:
            # pylint: disable=too-few-public-methods
            class HelpConfig:
                def __init__(self):
                    self.func = None
            self.parsed_options = HelpConfig()
        else:
            self.parsed_options = self.args.parse_args(argv)
        return self.parsed_options

    def print_help(self):
        self.args.print_help()

    def get_gitlab_instance(self):
        return gitlab.Gitlab.from_config(
            self.parsed_options.gitlab_instance,
            self.parsed_options.gitlab_config_file
        )

def as_existing_gitlab_projects(glb, users, project_template):
    """
    Convert list of users to list of projects.

    List of users (e.g. from UserListParameter) is converted to
    a tuple of user and project, formatted according to given
    project template.

    Unknown projects are skipped, warning message is printed.

    Returns a generator (yields).
    """

    for user in users:
        project_path = project_template.format(**user.row)

        try:
            project = mg.get_canonical_project(glb, project_path)
            yield user, project
        except gitlab.exceptions.GitlabGetError:
            print("WARNING: project {} not found!".format(project_path), file=sys.stderr)
            continue


@register_command('accounts')
def action_accounts(glb, users: UserListParameter()):
    """
    List accounts that were not found.
    """
    for _ in users:
        pass


@register_command('fork')
def action_fork(
        glb,
        users: UserListParameter(),
        from_project: ActionParameter(
            'from',
            required=True,
            metavar='REPO_PATH',
            help='Parent repository path.'
        ),
        to_project_template: ActionParameter(
            'to',
            required=True,
            metavar='REPO_PATH_WITH_FORMAT',
            help='Target repository path, including formatting characters from CSV columns.'
        ),
        hide_fork: ActionParameter(
            'hide-fork',
            default=False,
            action='store_true',
            help='Hide fork relationship.'
        )
    ):
    """
    Fork one repo multiple times.
    """

    from_project = mg.get_canonical_project(glb, from_project)

    for user in users:
        to_full_path = to_project_template.format(**user.row)
        to_namespace = os.path.dirname(to_full_path)
        to_name = os.path.basename(to_full_path)

        print("Forking {} to {}/{} for user {}".format(from_project.path_with_namespace,
                                                       to_namespace, to_name,
                                                       user.username))
        to_project = mg.fork_project_idempotent(glb, from_project, to_namespace, to_name)
        mg.wait_for_project_to_be_forked(glb, to_project)

        if hide_fork:
            mg.remove_fork_relationship(glb, to_project)


@register_command('protect')
def action_set_branch_protection(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        branch_name: ActionParameter(
            'branch',
            required=True,
            metavar='GIT_BRANCH',
            help='Git branch name to set protection on.'
        ),
        developers_can_merge: ActionParameter(
            'developers-can-merge',
            default=False,
            action='store_true',
            help='Allow developers to merge into this branch.'
        ),
        developers_can_push: ActionParameter(
            'developers-can-push',
            default=False,
            action='store_true',
            help='Allow developers to merge into this branch.'
        )
    ):
    """
    Set branch protection on multiple projects.
    """

    for _, project in as_existing_gitlab_projects(glb, users, project_template):
        branch = project.branches.get(branch_name)
        print("Setting protection on branch {} in {}".format(branch.name, project.path_with_namespace))
        branch.protect(developers_can_push=developers_can_push, developers_can_merge=developers_can_merge)


@register_command('unprotect')
def action_unprotect_branch(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        branch_name: ActionParameter(
            'branch',
            required=True,
            metavar='GIT_BRANCH',
            help='Git branch name to unprotect.'
        )
    ):
    """
    Unprotect branch on multiple projects.
    """

    for _, project in as_existing_gitlab_projects(glb, users, project_template):
        branch = project.branches.get(branch_name)
        print("Unprotecting branch {} on {}".format(branch.name, project.path_with_namespace))
        branch.unprotect()


@register_command('add-member')
def action_add_member(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        access_level: ActionParameter(
            'access-level',
            required=True,
            metavar='LEVEL',
            help='Access level: devel or reporter.'
        )
    ):
    """
    Add members to multiple projects.
    """

    if access_level == 'devel':
        level = gitlab.DEVELOPER_ACCESS
    elif access_level == 'reporter':
        level = gitlab.REPORTER_ACCESS
    else:
        raise Exception("Unsupported access level.")

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        try:
            print("Adding {} to {} (level {})".format(user.username, project.path_with_namespace, level))
            project.members.create({
                'user_id' : user.id,
                'access_level' : level,
            })
        except gitlab.GitlabCreateError as exp:
            if exp.response_code == http.HTTPStatus.CONFLICT:
                pass
            else:
                print(" -> error: {}".format(exp))


@register_command('get-file')
def action_get_file(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        remote_file_template: ActionParameter(
            'remote-file',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        local_file_template: ActionParameter(
            'local-file',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        branch: ActionParameter(
            'branch',
            default='master',
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        deadline: ActionParameter(
            'deadline',
            default='now',
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        blacklist: ActionParameter(
            'blacklist',
            default=None,
            metavar='BLACKLIST',
            help='Commit authors to ignore (regular expression).'
        )
    ):
    """
    Get file from multiple repositories.
    """

    if deadline == 'now':
        deadline = time.strftime('%Y-%m-%dT%H:%M:%S%z')

    if blacklist:
        filter = lambda commit: not re.fullmatch (blacklist, commit.author_email)
    else:
        filter = lambda commit: True

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        remote_file = remote_file_template.format(**user.row)
        local_file = local_file_template.format(**user.row)

        try:
            last_commit = mg.get_commit_before_deadline(glb, project, deadline, branch, filter)
        except Exception:
            print("No matching commit in {}.".format(project.path_with_namespace))
            continue

        current_content = mg.get_file_contents(glb, project, last_commit.id, remote_file)
        if current_content is None:
            print("File {} does not exist in {}.".format(remote_file, project.path_with_namespace))
        else:
            print("File {} in {} has {}B.".format(remote_file, project.path_with_namespace, len(current_content)))
            with open(local_file, "wb") as f:
                f.write(current_content)


@register_command('put-file')
def action_put_file(
        glb,
        users: UserListParameter(),
        dry_run: DryRunParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        from_file_template: ActionParameter(
            'from',
            required=True,
            metavar='LOCAL_FILE_PATH_WITH_FORMAT',
            help='Local file path, including formatting.'
        ),
        to_file_template: ActionParameter(
            'to',
            required=True,
            metavar='REMOTE_FILE_PATH_WITH_FORMAT',
            help='Remote file path, including formatting.'
        ),
        branch: ActionParameter(
            'branch',
            default='master',
            metavar='BRANCH',
            help='Branch to commit to, defaults to master.'
        ),
        commit_message_template: ActionParameter(
            'message',
            default='Updating {GL[target_filename]}',
            metavar='COMMIT_MESSAGE_WITH_FORMAT',
            help='Commit message, including formatting.'
        ),
        force_commit: ActionParameter(
            'force-commit',
            default=False,
            action='store_true',
            help='Do not check current file content, always upload.'
        )
    ):
    """
    Upload file to multiple repositories.
    """

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        from_file = from_file_template.format(**user.row)
        to_file = to_file_template.format(**user.row)
        extras = {
            'target_filename': to_file,
        }
        commit_message = commit_message_template.format(GL=extras, **user.row)

        from_file_content = pathlib.Path(from_file).read_text()

        commit_needed = force_commit
        if not force_commit:
            current_content = mg.get_file_contents(glb, project, branch, to_file)
            if current_content:
                commit_needed = current_content != from_file_content.encode('utf-8')
            else:
                commit_needed = True

        if commit_needed:
            print("Uploading {} to {} as {}".format(from_file, project.path_with_namespace, to_file))
            if not dry_run:
                mg.put_file_overwriting(glb, project, branch, to_file, from_file_content, commit_message)
        else:
            print("Not uploading {} to {} as there is no change.".format(from_file, project.path_with_namespace))


@register_command('get-last-pipeline')
def action_get_last_pipeline(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        branch: ActionParameter(
            'branch',
            default='master',
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        summary_only: ActionParameter(
            'summary-only',
            default=False,
            action='store_true',
            help='Print only summaries (ratio of states across projects)'
        )
    ):
    """
    Get pipeline status of multiple projects.
    """

    result = {}
    pipeline_states_only = []
    for _, project in as_existing_gitlab_projects(glb, users, project_template):
        pipelines = project.pipelines.list()
        if len(pipelines) == 0:
            result[project.path_with_namespace] = {
                "status": "none"
            }
            pipeline_states_only.append("none")
            continue

        last_pipeline = pipelines[0]

        entry = {
            "status": last_pipeline.status,
            "id": last_pipeline.id,
            "commit": last_pipeline.sha,
            "jobs": [],
        }
        pipeline_states_only.append(last_pipeline.status)

        for job in last_pipeline.jobs.list():
            entry["jobs"].append({
                "status": job.status,
                "id": job.id,
                "name": job.name,
            })

        result[project.path_with_namespace] = entry

    if summary_only:
        summary_by_overall_status = collections.Counter(pipeline_states_only)
        states_len = len(pipeline_states_only)
        for state, count in summary_by_overall_status.most_common():
            print("{}: {} ({:.0f}%)".format(state, count, 100 * count / states_len))
        print("total: {}".format(states_len))
    else:
        print(json.dumps(result, indent=4))


@register_command('clone')
def action_clone(
        glb,
        users: UserListParameter(False),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        local_path_template: ActionParameter(
            'to',
            required=True,
            metavar='LOCAL_PATH_WITH_FORMAT',
            help='Local repository path, including formatting characters from CSV columns.'
        ),
        branch: ActionParameter(
            'branch',
            default='master',
            metavar='BRANCH',
            help='Branch to clone, defaults to master.'
        ),
        commit: ActionParameter(
            'commit',
            default=None,
            metavar='COMMIT_WITH_FORMAT',
            help='Commit to reset to after clone.'
        ),
        deadline: ActionParameter(
            'deadline',
            default='now',
            metavar='YYYY-MM-DDTHH:MM:SSZ',
            help='Submission deadline, take last commit before deadline (defaults to now).'
        ),
        blacklist: ActionParameter(
            'blacklist',
            default=None,
            metavar='BLACKLIST',
            help='Commit authors to ignore (regular expression).'
        )
    ):
    """
    Clone multiple repositories.
    """

    # FIXME: commit and deadline are mutually exclusive

    if deadline == 'now':
        deadline = time.strftime('%Y-%m-%dT%H:%M:%S%z')

    if blacklist:
        filter = lambda commit: not re.fullmatch (blacklist, commit.author_email)
    else:
        filter = lambda commit: True

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        project = mg.get_canonical_project(glb, project_template.format(**user.row))
        local_path = local_path_template.format(**user.row)

        if commit:
            last_commit = project.commits.get(commit.format(**user.row))
        else:
            last_commit = mg.get_commit_before_deadline(glb, project, deadline, branch, filter)
        mg.clone_or_fetch(glb, project, local_path)
        mg.reset_to_commit(local_path, last_commit.id)


@register_command('deadline-commit')
def action_deadline_commits(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
        branch: ActionParameter(
            'branch',
            default='master',
            metavar='BRANCH',
            help='Branch name, defaults to master.'
        ),
        prefer_tag: ActionParameter(
            'prefer-tag',
            default=None,
            metavar='TAG',
            help='Prefer commit with this tag (but also before deadline).'
        ),
        deadline: ActionParameter(
            'deadline',
            default='now',
            metavar='YYYY-MM-DDTHH:MM:SSZ',
            help='Submission deadline, take last commit before deadline (defaults to now).'
        ),
        blacklist: ActionParameter(
            'blacklist',
            default=None,
            metavar='BLACKLIST',
            help='Commit authors to ignore (regular expression).'
        ),
        output_header: ActionParameter(
            'first-line',
            default='login,commit',
            metavar='OUTPUT_HEADER',
            help='First line for the output.'
        ),
        output_template: ActionParameter(
            'format',
            default='{login},{commit.id}',
            metavar='OUTPUT_ROW_WITH_FORMAT',
            help='Formatting for the output row, defaults to {login},{commit.id}.'
        ),
        output_filename: ActionParameter(
            'output',
            default=None,
            metavar='OUTPUT_FILENAME',
            help='Output file, defaults to stdout.'
        )
    ):
    """
    Get last commits before deadline.
    """

    if output_filename:
        output = open(output_filename, 'w')
    else:
        output = sys.stdout

    if deadline == 'now':
        deadline = time.strftime('%Y-%m-%dT%H:%M:%S%z')

    if blacklist:
        filter = lambda commit: not re.fullmatch (blacklist, commit.author_email)
    else:
        filter = lambda commit: True

    print(output_header, file=output)

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        last_commit = mg.get_commit_before_deadline(glb, project, deadline, branch, filter, prefer_tag)

        line = output_template.format(commit=last_commit, **user.row)
        print(line, file=output)

    if output_filename:
        output.close()


@register_command('commit-stats')
def action_commit_stats(
        glb,
        users: UserListParameter(),
        project_template: ActionParameter(
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, including formatting characters from CSV columns.'
        ),
    ):
    """
    Get basic added/removed lines for projects.
    """

    result = []
    processed_projects = {}

    for user, project in as_existing_gitlab_projects(glb, users, project_template):
        project_path = project_template.format(**user.row)
        if project_path in processed_projects:
            continue
        processed_projects[project_path] = True

        commits = project.commits.list(all=True, as_list=False)
        commit_details = {}
        for c in commits:
            info = project.commits.get(c.id)
            commit_details[c.id] = {
                'parents': info.parent_ids,
                'subject': info.title,
                'line_stats': info.stats,
                'author_email': info.author_email,
                'author_date': info.authored_date,
            }

        result.append({
            'project': project.path_with_namespace,
            'commits': commit_details,
        })

    print(json.dumps(result, indent=4))


def main():
    locale.setlocale(locale.LC_ALL, '')

    cli = CommandParser()

    for cmd in get_registered_commands():
        cli.add_command(cmd['name'], cmd['func'])

    config = cli.parse_args(sys.argv[1:])

    if config.func is None:
        cli.print_help()
        return

    glb = cli.get_gitlab_instance()
    config.func(glb, config)

if __name__ == '__main__':
    main()
