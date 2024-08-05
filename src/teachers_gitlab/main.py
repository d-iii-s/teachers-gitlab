#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Charles University

"""
Teachers GitLab for mass actions on GitLab

Utilities to help you manage multiple repositories at once.
Targets teachers that need to manage separate repository for each
student and massively fork, clone or upload files to them.
"""

import argparse
import collections
import csv
import http
import json
import locale
import logging
import os
import pathlib
import re
import sys
import textwrap

import gitlab

import teachers_gitlab.utils as mg

_registered_commands = []


def register_command(name, brief=None):
    """
    Decorator for function representing an actual command.

    :param name: Command name (as specified by the user).
    """

    def decorator(func):
        """
        Actual decorator (because we need to process arguments).
        """
        _registered_commands.append({
            'name': name,
            'brief': brief,
            'func': func
        })
        func._command_name = name

        def wrapper(*args, **kwargs):
            """
            Wrapper calling the original function.
            """
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_registered_commands():
    """
    Return list of commands registers so far.
    """
    return _registered_commands[:]


class Parameter:
    """
    Base class for parameter annotation.
    """

    def __init__(self):
        pass

    def register(self, argument_name, subparser):
        """
        Callback to add itself to the argparse subparser.

        :param argument_name: Used for dest in argparse.
        :param subparser: Parser to register arguments with.
        """

    def get_value(self, argument_name, glb, parsed_options):
        """
        Get actual value of the parameter.

        :param argument_name: dest as used by argparse.
        :param glb: Initialized GitLab instance.
        :param parsed_options: Object of parsed option from argparse.
        """


class GitlabInstanceParameter(Parameter):
    """
    Parameter annotation to mark GitLab instance object.
    """

    def __init__(self):
        Parameter.__init__(self)

    def get_value(self, argument_name, glb, parsed_options):
        return glb


class LoggerParameter(Parameter):
    """
    Parameter annotation to mark command logger.
    """

    def __init__(self):
        Parameter.__init__(self)

    def get_value(self, argument_name, glb, parsed_options):
        return logging.getLogger(parsed_options.command_name_)


class IntrospectionParameter(Parameter):
    """
    Parameter annotation to introspect the parser itself.
    """

    def __init__(self):
        Parameter.__init__(self)

    def get_value(self, argument_name, glb, parsed_options):
        return parsed_options.parser


class ActionEntries:
    def __init__(self, entries: list):
        self.entries = entries
        self.logger = logging.getLogger('action-entries')

    def as_items(self):
        """
        Return entries as-is.
        """
        for entry in self.entries:
            yield entry

    def as_gitlab_user(self, entry, glb: gitlab.client.Gitlab, login_column: str):
        if user_login := entry.get(login_column):
            matching_users = glb.users.list(username=user_login, iterator=True)
            if user_object := next(matching_users, None):
                return user_object
            else:
                self.logger.warning(f"User {user_login} not found.")
        else:
            self.logger.error(f"Missing or empty '{login_column}' in {entry}.")

        # No corresponding user for the entry.
        return None

    def as_gitlab_users(self, glb: gitlab.client.Gitlab, login_column: str):
        """
        Converts entries to GitLab users.

        Each entry is converted to a tuple (entry, user), with the user
        login obtained from entry login column. For users that do not
        exist, None is returned and a warning message is printed.

        :param glb: GitLab instance to use
        :param login_column: name of the entry column containing user login
        :return: generator of (entry, user)
        """
        for entry in self.entries:
            yield entry, self.as_gitlab_user(entry, glb, login_column)

    def as_gitlab_projects(
        self, glb: gitlab.client.Gitlab, project_template: str,
        allow_duplicates: bool = False
    ):
        """
        Converts entries to GitLab projects.

        Each entry is converted to a tuple (entry, project), with the project
        path obtained by formatting :project_template: using entry data.
        For projects that cannot be found, None is returned and a warning
        message is printed.

        :param glb: GitLab instance to use
        :param project_template: template for generating project names using entry data
        :param allow_duplicates: whether to return duplicate projects, defaults to False
        :return: generator of (entry, project)
        """

        projects_by_path = {}
        for entry in self.entries:
            project_path = project_template.format(**entry)
            if project := projects_by_path.get(project_path):
                # We have seen the project before, but will return it only if
                # we allow duplicates to be produced. Otherwise, move on.
                if allow_duplicates:
                    yield entry, project

                continue

            # We have not seen the project before, look it up.
            try:
                project = mg.get_canonical_project(glb, project_path)
                projects_by_path[project_path] = project
                yield entry, project

            except gitlab.exceptions.GitlabGetError:
                self.logger.warning(f"Project '{project_path}' not found.")


class ActionEntriesParameter(Parameter):
    """
    Parameter annotation to mark action entries for template expansion. If the
    entries represent users, they must contain a column with user login. The
    entries are read from standard input if '-' is given as file name.
    """
    def __init__(self):
        Parameter.__init__(self)

    def register(self, argument_name, subparser):
        subparser.add_argument(
            '--users', '--entries',
            required=True,
            dest='entries_csv',
            metavar='LIST.csv',
            help='CSV with entries on which to perform an action'
        )

    def get_value(self, argument_name, glb, parsed_options):
        def _load_entries(csv_file):
            reader = csv.DictReader(csv_file)
            logger.debug(f"Loaded entries with columns {reader.fieldnames}")
            return list(reader)

        logger = logging.getLogger('action-entries')
        if (parsed_options.entries_csv == '-'):
            entries = _load_entries(sys.stdin)
        else:
            with open(parsed_options.entries_csv) as entries_csv:
                entries = _load_entries(entries_csv)

        return ActionEntries(entries)


class ActionParameter(Parameter):
    """
    Parameter annotation to create corresponding CLI option.
    """

    def __init__(self, name, **kwargs):
        Parameter.__init__(self)
        self.name = name
        self.extra_args = kwargs

    @staticmethod
    def _dest_name(argument_name):
        return 'arg_' + argument_name

    def register(self, argument_name, subparser):
        subparser.add_argument(
            '--' + self.name,
            dest=self._dest_name(argument_name),
            **self.extra_args
        )

    def get_value(self, argument_name, glb, parsed_options):
        return getattr(parsed_options, self._dest_name(argument_name))


class DateTimeActionParameter(ActionParameter):
    """
    Parameter annotation to create a datetime action parameter.
    """
    def __init__(self, name, **kwargs):
        ActionParameter.__init__(
            self, name, type=mg.get_timestamp, **kwargs
        )


class DryRunActionParameter(ActionParameter):
    """
    Parameter annotation to create an option for enabling dry run.
    """

    def __init__(self):
        ActionParameter.__init__(
            self,
            'dry-run',
            default=False,
            action='store_true',
            help='Simulate but do not make any real changes.'
        )


class LoginColumnActionParameter(ActionParameter):
    """
    Parameter annotation to create an option for specifying login column.
    """
    def __init__(self):
        ActionParameter.__init__(
            self,
            'login-column',
            default='login',
            metavar='COLUMN_NAME',
            help='Column name with user login name.'
        )


class RequiredProjectActionParameter(ActionParameter):
    def __init__(self):
        ActionParameter.__init__(
            self,
            'project',
            required=True,
            metavar='PROJECT_PATH_WITH_FORMAT',
            help='Project path, formatted from CSV columns.'
        )


class AccessLevelActionParameter(ActionParameter):
    """
    Parameter annotation to create an access level action parameter.
    """

    def __init__(self, name, compat_flags=None, **kwargs):
        ActionParameter.__init__(
            self, name,
            # Provide available access level names as choices.
            choices=[level.name for level in list(gitlab.const.AccessLevel)],
            # Accept both lower and upper case access level names.
            type=str.upper,
            **kwargs
        )
        self.compat_flags = compat_flags if compat_flags else []

    def register(self, argument_name, subparser):
        # Compatibility flags are mutually exclusive with each
        # other and the original parameter.
        if self.compat_flags:
            subparser = subparser.add_mutually_exclusive_group()

        ActionParameter.register(self, argument_name, subparser)

        # Compatibility flags set the original parameter value
        # to predefined access levels.
        for flag in self.compat_flags:
            subparser.add_argument(
                '--' + flag["name"],
                dest=self._dest_name(argument_name),
                action='store_const',
                const=flag["level"],
                help=flag["help"]
            )

    def get_value(self, argument_name, glb, parsed_options):
        # The value may be a string or AccessLevel instance. Make sure to return the latter.
        value = ActionParameter.get_value(self, argument_name, glb, parsed_options)
        return gitlab_get_access_level(value)


def gitlab_get_access_level(level):
    """
    Looks up a GitLab AccessLevel instance.
    """
    if isinstance(level, str):
        return gitlab.const.AccessLevel[level]
    elif isinstance(level, int):
        return gitlab.const.AccessLevel(level)
    elif isinstance(level, gitlab.const.AccessLevel):
        return level
    else:
        raise ValueError(f"invalid access level: {level}")


def gitlab_extract_access_level(gl_object, access_type):
    access_level_value = getattr(gl_object, access_type)[0]['access_level']
    return gitlab_get_access_level(access_level_value)


class CommandParser:
    """
    Wrapper for argparse for Teachers GitLab.
    """

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

        self.subcommands = {}

    def add_command(self, name, callback_func):
        """
        Add whole subcommand.
        """

        short_help = callback_func.__doc__
        if short_help is not None:
            short_help = textwrap.dedent(short_help.strip())
        parser = self.args_sub.add_parser(
            name,
            description=short_help,
            parents=[self.args_common]
        )
        for dest, param in callback_func.__annotations__.items():
            param.register(dest, parser)

        def wrapper(glb, cfg, callback):
            kwargs = {}
            for dest, param in callback.__annotations__.items():
                kwargs[dest] = param.get_value(dest, glb, cfg)
            callback(**kwargs)

        parser.set_defaults(func=lambda glb, cfg: wrapper(glb, cfg, callback_func))
        parser.set_defaults(command_name_=name)
        parser.set_defaults(parser=self)

        self.subcommands[name] = parser

    def parse_args(self, argv):
        """
        Wrapper around argparse.parse_args.
        """

        if len(argv) < 1:
            self.parsed_options = self.args.parse_args(['help'])
        else:
            self.parsed_options = self.args.parse_args(argv)

        return self.parsed_options

    def print_help(self, subcommand=None):
        """
        Wrapper around argparse.print_help.
        """

        if subcommand is None:
            self.args.print_help()
        else:
            self.subcommands[subcommand].print_help()

    def get_gitlab_instance(self):
        return gitlab.Gitlab.from_config(
            self.parsed_options.gitlab_instance,
            self.parsed_options.gitlab_config_file
        )


@register_command('accounts', 'Validate accounts existence')
def action_accounts(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    login_column: LoginColumnActionParameter(),
    show_summary: ActionParameter(
        'show-summary',
        default=False,
        action='store_true',
        help='Show summary numbers.'
    ),
    check_renamed_accounts: ActionParameter(
        'check-renamed-accounts',
        default=False,
        action='store_true',
        help='Try for possibly renamed accounts (e.g. with 1 appended to login).'
    )
):
    """
    List accounts that were not found.
    """
    users = list(entries.as_gitlab_users(glb, login_column))
    if check_renamed_accounts:
        for entry in entries.as_items():
            if not (user_login := entry.get(login_column)):
                continue
            matching_users = glb.users.list(username=user_login, iterator=True)
            if next(matching_users, None):
                continue
            for suffix in ['1', '2', '3', '11']:
                login_with_suffix = user_login + suffix
                matching_users = glb.users.list(username=login_with_suffix, iterator=True)
                if not (user_obj := next(matching_users, None)):
                    continue
                logger.warning("User %s not found, but account for %s exists.", user_login, login_with_suffix)
    if show_summary:
        entries_total = len(users)
        users_found = len([u for _, u in users if u])
        print('Total: {}, Not-found: {}, Ok: {}'.format(
            entries_total, entries_total - users_found, users_found
        ))


def get_regex_blacklist_filter(blacklist_re, func):
    def accept_all(_):
        return True

    def reject_blacklist_matches(obj):
        return not blacklist_pattern.fullmatch(func(obj))

    if blacklist_re:
        blacklist_pattern = re.compile(blacklist_re)
        return reject_blacklist_matches
    else:
        return accept_all


def get_commit_author_email_filter(blacklist):
    return get_regex_blacklist_filter(blacklist, lambda commit: commit.author_email)


@register_command('clone', 'Clone a project to a local directory')
def action_clone(
    glb: GitlabInstanceParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    local_path_template: ActionParameter(
        'to',
        required=True,
        metavar='LOCAL_PATH_WITH_FORMAT',
        help='Local repository path, formatted from CSV columns.'
    ),
    branch: ActionParameter(
        'branch',
        default='master',
        metavar='BRANCH',
        help='Branch to clone, defaults to master.'
    ),
    commit_template: ActionParameter(
        'commit',
        default=None,
        metavar='COMMIT_WITH_FORMAT',
        help='Commit to reset to after clone.'
    ),
    deadline: DateTimeActionParameter(
        'deadline',
        default='now',
        metavar='YYYY-MM-DDTHH:MM:SSZ',
        help='Submission deadline (defaults to now).'
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

    commit_filter = get_commit_author_email_filter(blacklist)
    for entry, project in entries.as_gitlab_projects(glb, project_template):
        if commit_template:
            last_commit = project.commits.get(commit_template.format(**entry))
        else:
            last_commit = mg.get_commit_before_deadline(
                glb, project, deadline, branch, commit_filter
            )

        local_path = local_path_template.format(**entry)
        mg.clone_or_fetch(glb, project, local_path)
        mg.reset_to_commit(local_path, last_commit.id)

@register_command('create-group', 'Create new group')
def create_group(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    group_name_template: ActionParameter(
        'name',
        required=False,
        metavar='NAME_OF_THE_GROUP',
        help='Group name (title), formatted from CSV columns.'
    ),
    path_template: ActionParameter(
        'path',
        required=True,
        metavar='GROUP_PATH',
        help='String name of the path to the created group, formatted from CSV columns.'
    ),
    parent_group_template: ActionParameter(
        'from',
        required=True,
        metavar='REPO_PATH_WITH_FORMAT',
        help='Parent repository path, formatted from CSV columns.'
    ),
):
    for entry in entries.as_items():
        from_group = mg.get_canonical_group(glb, parent_group_template.format(**entry))

        path_name = path_template.format(**entry)
        group_path = from_group.full_path + '/' + path_name

        if group_name_template:
            group_name = group_name_template.format(**entry)
        else:
            group_name = path_name

        if mg.is_existing_group(glb, group_path):
            logger.info("Group %s already exists.", group_path)
            continue

        logger.info(
            "Creating group %s in %s.",
            group_name,
            from_group.full_path,
        )

        glb.groups.create({
            'name': group_name,
            'path': path_name,
            'parent_id': from_group.id
        })

@register_command('fork', 'Fork a project')
def action_fork(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    login_column: LoginColumnActionParameter(),
    from_project_template: ActionParameter(
        'from',
        required=True,
        metavar='REPO_PATH_WITH_FORMAT',
        help='Parent repository path, formatted from CSV columns.'
    ),
    to_project_template: ActionParameter(
        'to',
        required=True,
        metavar='REPO_PATH_WITH_FORMAT',
        help='Target repository path, formatted from CSV columns.'
    ),
    hide_fork: ActionParameter(
        'hide-fork',
        default=False,
        action='store_true',
        help='Hide fork relationship.'
    ),
    include_nonexistent: ActionParameter(
        'include-invalid-users',
        default=False,
        action='store_true',
        help='Fork even for invalid (e.g. not found) users.'
    )
):
    """
    Fork one (or more) repositories multiple times.
    """

    for entry, user in entries.as_gitlab_users(glb, login_column):
        if not user and not include_nonexistent:
            # Skip forking for non-existent users
            continue

        from_project = mg.get_canonical_project(glb, from_project_template.format(**entry))

        user_name = user.username if user else entry.get(login_column)
        to_full_path = to_project_template.format(**entry)
        to_namespace = os.path.dirname(to_full_path)
        to_name = os.path.basename(to_full_path)

        logger.info(
            "Forking %s to %s/%s for user %s",
            from_project.path_with_namespace,
            to_namespace, to_name, user_name
        )

        to_project = mg.fork_project_idempotent(glb, from_project, to_namespace, to_name)
        mg.wait_for_project_to_be_forked(glb, to_project)

        if hide_fork:
            mg.remove_fork_relationship(glb, to_project)


@register_command('protect', 'Protect a Git branch')
def action_protect_branch(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    branch_name: ActionParameter(
        'branch',
        required=True,
        metavar='GIT_BRANCH',
        help='Git branch name to set protection on.'
    ),
    merge_access_level: AccessLevelActionParameter(
        'merge-access-level',
        default=gitlab.const.AccessLevel.MAINTAINER,
        help="Access level required to merge to this branch. Defaults to 'MAINTAINER'.",
        compat_flags=[{
            "name": "developers-can-merge",
            "help": "DEPRECATED: Allow developers to merge to this branch.",
            "level": gitlab.const.AccessLevel.DEVELOPER
        }]
    ),
    push_access_level: AccessLevelActionParameter(
        'push-access-level',
        default=gitlab.const.AccessLevel.MAINTAINER,
        help="Access level required to push to this branch. Defaults to 'MAINTAINER'.",
        compat_flags=[{
            "name": "developers-can-push",
            "help": "DEPRECATED: Allow developers to push to this branch.",
            "level": gitlab.const.AccessLevel.DEVELOPER
        }]
    )
):
    """
    Set branch protection on multiple projects.
    """

    for _, project in entries.as_gitlab_projects(glb, project_template):
        logger.info(
            "Protecting branch '%s' in %s",
            branch_name, project.path_with_namespace
        )

        try:
            _project_protect_branch(
                project, branch_name, merge_access_level, push_access_level,
                logger
            )
        except gitlab.GitlabError as exp:
            logger.error("- Failed to protect branch: %s", exp)


def _project_protect_branch(project, branch_name, merge_access_level, push_access_level, logger):
    def branch_get_merge_access_level(branch):
        return gitlab_extract_access_level(branch, 'merge_access_levels')

    def branch_get_push_access_level(branch):
        return gitlab_extract_access_level(branch, 'push_access_levels')

    # Protected branches cannot be modified and saved (they lack the SaveMixin).
    # If a protected branch already exists and does not have the desired access
    # levels, it needs to be deleted and created anew.
    if protected_branch := _project_get_protected_branch(project, branch_name):
        existing_merge_level = branch_get_merge_access_level(protected_branch)
        existing_push_level = branch_get_push_access_level(protected_branch)
        if existing_merge_level == merge_access_level and existing_push_level == push_access_level:
            logger.debug(
                "- Already exists with '%s/%s' merge/push access, skipping.",
                merge_access_level.name, push_access_level.name
            )
            return

        logger.info(
            "- Already exists with '%s/%s' merge/push access, updating to '%s/%s'.",
            existing_merge_level.name, existing_push_level.name,
            merge_access_level.name, push_access_level.name
        )
        protected_branch.delete()

    project.protectedbranches.create({
        'name': branch_name,
        'merge_access_level': merge_access_level,
        'push_access_level': push_access_level
    })


@register_command('unprotect', 'Unprotect a Git branch')
def action_unprotect_branch(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
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

    for _, project in entries.as_gitlab_projects(glb, project_template):
        logger.info(
            "Unprotecting branch '%s' in %s",
            branch_name, project.path_with_namespace
        )

        try:
            _project_unprotect_branch(project, branch_name, logger)
        except gitlab.GitlabError as exp:
            logger.error("- Failed to unprotect branch: %s", exp)


def _project_unprotect_branch(project, branch_name, logger):
    if protected_branch := _project_get_protected_branch(project, branch_name):
        protected_branch.delete()
    else:
        logger.debug("- Protected branch '%s' not found.", branch_name)


def _project_get_protected_branch(project, branch_name):
    try:
        return project.protectedbranches.get(branch_name)
    except gitlab.exceptions.GitlabGetError:
        # There is no such protected branch.
        return None


@register_command('create-tag', 'Create a Git tag')
def action_create_tag(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    tag_name: ActionParameter(
        'tag',
        required=True,
        metavar='TAG_NAME',
        help='Git tag name.'
    ),
    ref_name_template: ActionParameter(
        'ref',
        required=True,
        metavar='GIT_BRANCH_OR_COMMIT_WITH_TEMPLATE',
        help='Git branch name (tip) or commit to tag, formatted from CSV columns.'
    ),
    commit_message_template: ActionParameter(
        'message',
        default=None,
        metavar='COMMIT_MESSAGE_WITH_FORMAT',
        help='Commit message, formatted from CSV columns.'
    ),
):
    """
    Create a tag on a given commit or branch tip.
    """

    for entry, project in entries.as_gitlab_projects(glb, project_template):
        ref_name = ref_name_template.format(**entry)
        params = {
            'tag_name': tag_name,
            'ref': ref_name,
        }

        if commit_message_template:
            extras = {
                'tag': tag_name,
            }
            params['message'] = commit_message_template.format(GL=extras, **entry)

        logger.info("Creating tag %s on %s in %s", tag_name, ref_name, project.path_with_namespace)
        try:
            mg.create_tag(glb, project, params)
        except gitlab.exceptions.GitlabCreateError as exp:
            if (exp.response_code == http.HTTPStatus.BAD_REQUEST) and exp.error_message.endswith("already exists"):
                pass
            else:
                raise


@register_command('protect-tag', 'Set tag protection')
def action_protect_tag(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    tag_name: ActionParameter(
        'tag',
        required=True,
        metavar='GIT_TAG',
        help='Git tag name to set protection on.'
    ),
    create_access_level: AccessLevelActionParameter(
        'create-access-level',
        default=gitlab.const.AccessLevel.NO_ACCESS,
        help="Access level required to create this tag. Defaults to 'NO_ACCESS'.",
        compat_flags=[
            {
                "name": "developers-can-create",
                "help": "DEPRECATED: Allow developers to create this tag.",
                "level": gitlab.const.AccessLevel.DEVELOPER
            },
            {
                "name": "maintainers-can-create",
                "help": "DEPRECATED: Allow maintainers to create this tag.",
                "level": gitlab.const.AccessLevel.MAINTAINER
            }
        ]
    )
):
    """
    Set tag protection on multiple projects.
    """

    for _, project in entries.as_gitlab_projects(glb, project_template):
        logger.info(
            "Protecting tag '%s' in %s",
            tag_name, project.path_with_namespace
        )

        try:
            _project_protect_tag(project, tag_name, create_access_level, logger)
        except gitlab.GitlabError as exp:
            logger.error("- Failed to protect tag: %s", exp)


def _project_protect_tag(project, tag_name, create_access_level, logger):
    def tag_get_create_access_level(tag):
        return gitlab_extract_access_level(tag, 'create_access_levels')

    # Protected tags cannot be modified and saved (they lack the SaveMixin).
    # If a protected tag already exists and does not have the desired access
    # levels, it needs to be deleted and created anew.
    if protected_tag := _project_get_protected_tag(project, tag_name):
        existing_create_level = tag_get_create_access_level(protected_tag)
        if existing_create_level == create_access_level:
            logger.debug(
                "- Already exists with '%s' create access, skipping.",
                create_access_level.name
            )
            return

        logger.info(
            "- Already exists with '%s' create access, updating to '%s'.",
            existing_create_level.name, create_access_level.name
        )
        protected_tag.delete()

    project.protectedtags.create({
        'name': tag_name,
        'create_access_level': create_access_level
    })


@register_command('unprotect-tag', 'Unset tag protection')
def action_unprotect_tag(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    tag_name: ActionParameter(
        'tag',
        required=True,
        metavar='GIT_TAG',
        help='Git tag name to unprotect.'
    ),
):
    """
    Unset tag protection on multiple projects.
    """

    for _, project in entries.as_gitlab_projects(glb, project_template):
        logger.info(
            "Unprotecting tag '%s' in %s",
            tag_name, project.path_with_namespace
        )

        try:
            _project_unprotect_tag(project, tag_name, logger)
        except gitlab.GitlabError as exp:
            logger.error("- Failed to unprotect tag: %s", exp)


def _project_unprotect_tag(project, tag_name, logger):
    if protected_tag := _project_get_protected_tag(project, tag_name):
        protected_tag.delete()
    else:
        logger.debug("- Protected tag '%s' not found.", tag_name)


def _project_get_protected_tag(project, tag_name):
    try:
        return project.protectedtags.get(tag_name)
    except gitlab.exceptions.GitlabGetError:
        # There is no such protected tag.
        return None


@register_command('get-members', 'Get project members')
def action_members(
    glb: GitlabInstanceParameter(),
    project: ActionParameter(
        'project',
        required=True,
        metavar='PROJECT_PATH',
        help='Project path.'
    ),
    inherited: ActionParameter(
        'inherited',
        default=False,
        action='store_true',
        help='Show inherited members.'
    )
):
    """
    Get members of a project.
    """

    project = mg.get_canonical_project(glb, project)
    members = project.members_all if inherited else project.members

    print('login,name')
    for member in members.list(all=True, iterator=True):
        print(f"{member.username},{member.name}")


@register_command('add-member', 'Add a project member')
def action_add_member(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    login_column: LoginColumnActionParameter(),
    dry_run: DryRunActionParameter(),
    project_template: RequiredProjectActionParameter(),
    access_level: AccessLevelActionParameter(
        'access-level',
        required=True,
        help="Access level granted to the member in the project."
    )
):
    """
    Add members to multiple projects.
    """

    for entry, project in entries.as_gitlab_projects(glb, project_template, allow_duplicates=True):
        if user := entries.as_gitlab_user(entry, glb, login_column):
            logger.info(
                "Adding %s (%s) to %s",
                user.username, access_level.name, project.path_with_namespace
            )

            if dry_run:
                continue

            try:
                _project_add_member(project, user, access_level, logger)
            except gitlab.GitlabError as exp:
                logger.error("- Failed to add member: %s", exp)


def _project_add_member(project, user, access_level, logger):
    if member := _project_get_member(project, user):
        # If a member already exists with correct access level, do nothing,
        # otherwise update the access level (project member attributes can
        # be updated and saved).
        existing_access_level = gitlab_get_access_level(member.access_level)
        if existing_access_level == access_level:
            logger.debug(
                "- Already exists with '%s' access, skipping.",
                access_level.name
            )
            return

        logger.info(
            "- Already exists with '%s' access, updating to '%s'.",
            existing_access_level.name, access_level.name
        )
        member.access_level = access_level
        member.save()

    else:
        # The user is not a member of the project, create a new member.
        project.members.create({
            'user_id': user.id,
            'access_level': access_level,
        })


@register_command('remove-member', 'Remove project member')
def action_remove_member(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    login_column: LoginColumnActionParameter(),
    dry_run: DryRunActionParameter(),
    project_template: RequiredProjectActionParameter()
):
    """
    Remove members from multiple projects.
    """

    for entry, project in entries.as_gitlab_projects(glb, project_template, allow_duplicates=True):
        if user := entries.as_gitlab_user(entry, glb, login_column):
            logger.info(
                "Removing %s from %s", user.username, project.path_with_namespace
            )

            if dry_run:
                continue

            try:
                _project_remove_member(project, user, logger)
            except gitlab.GitlabError as exp:
                logger.error("- Failed to remove member: %s", exp)


def _project_remove_member(project, user, logger):
    if member := _project_get_member(project, user):
        member.delete()
    else:
        logger.debug("- Member '%s' not found.", user.username)


def _project_get_member(project, user):
    try:
        return project.members.get(user.id)
    except gitlab.GitlabGetError:
        # There is no such member in the project.
        return None


@register_command('project-settings', 'Change project settings')
def action_project_settings(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    dry_run: DryRunActionParameter(),
    project_template: RequiredProjectActionParameter(),
    mr_default_target: ActionParameter(
        'merge-request-default-target',
        default=None,
        choices=['self', 'upstream'],
        help='Which project to merge to by default.',
    ),
    description: ActionParameter(
        'description',
        metavar="DESCRIPTION_TEXT",
        default=None,
        help='The description of the project, formatted from CSV columns.'
    )
):
    """
    Change project settings.
    """

    change_mr_default_target = mr_default_target is not None
    mr_default_target_is_self = mr_default_target == 'self'

    change_description = description is not None

    for entry, project in entries.as_gitlab_projects(glb, project_template):
        if change_mr_default_target:
            is_self = project.mr_default_target_self
            logger.debug("Project %s: mr_default_target_self=%s.", project.path_with_namespace, is_self)
            if mr_default_target_is_self != is_self:
                if not dry_run:
                    project.mr_default_target_self = mr_default_target_is_self
                    project.save()
                logger.info("Changed default merge request target in %s to %s", project.path_with_namespace, mr_default_target)
            else:
                logger.info("Default merge request target in %s is already set to %s", project.path_with_namespace, mr_default_target)
        if change_description:
            new_description = description.format(**entry)
            if not dry_run:
                project.description = new_description
                project.save()
            logger.info("Changed description to %s", new_description)



@register_command('get-file', 'Fetch given files')
def action_get_file(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    remote_file_template: ActionParameter(
        'remote-file',
        required=True,
        metavar='REMOTE_FILE_PATH_WITH_FORMAT',
        help='Remote file path, formatted from CSV columns..'
    ),
    local_file_template: ActionParameter(
        'local-file',
        required=True,
        metavar='LOCAL_FILE_PATH_WITH_FORMAT',
        help='Local file path, formatted from CSV columns.'
    ),
    branch: ActionParameter(
        'branch',
        default='master',
        metavar='BRANCH_WITH_FORMAT',
        help='Repository branch, formatted from CSV columns.'
    ),
    deadline: DateTimeActionParameter(
        'deadline',
        default='now',
        metavar='YYYY-MM-DDTHH:MM:SSZ',
        help='Submission deadline (defaults to now).'
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

    commit_filter = get_commit_author_email_filter(blacklist)
    for entry, project in entries.as_gitlab_projects(glb, project_template):
        try:
            last_commit = mg.get_commit_before_deadline(
                glb, project, deadline, branch, commit_filter
            )
        except gitlab.exceptions.GitlabGetError:
            logger.error("No matching commit in %s", project.path_with_namespace)
            continue

        remote_file = remote_file_template.format(**entry)
        current_content = mg.get_file_contents(glb, project, last_commit.id, remote_file)
        if current_content is None:
            logger.error(
                "File %s does not exist in %s",
                remote_file, project.path_with_namespace
            )
        else:
            logger.info(
                "File %s in %s has %dB.",
                remote_file, project.path_with_namespace, len(current_content)
            )

            local_file = local_file_template.format(**entry)
            with open(local_file, "wb") as f:
                f.write(current_content)


@register_command('put-file', 'Mass file upload')
def action_put_file(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    dry_run: DryRunActionParameter(),
    project_template: RequiredProjectActionParameter(),
    local_file_template: ActionParameter(
        'from',
        required=True,
        metavar='LOCAL_FILE_PATH_WITH_FORMAT',
        help='Local file path, formatted from CSV columns.'
    ),
    remote_file_template: ActionParameter(
        'to',
        required=True,
        metavar='REMOTE_FILE_PATH_WITH_FORMAT',
        help='Remote file path, formatted from CSV columns.'
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
        help='Commit message, formatted from CSV columns.'
    ),
    force_commit: ActionParameter(
        'force-commit',
        default=False,
        action='store_true',
        help='Do not check current file content, always upload.'
    ),
    skip_missing_file: ActionParameter(
        'skip-missing-files',
        default=False,
        action='store_true',
        help='Do not fail when file-to-be-uploaded is missing.'
    ),
    only_once: ActionParameter(
        'once',
        default=False,
        action='store_true',
        help='Upload file only if it is not present.'
    )
):
    """
    Upload file to multiple repositories.
    """

    if only_once and force_commit:
        logger.error("--force-commit and --once together does not make sense, aborting.")
        return

    for entry, project in entries.as_gitlab_projects(glb, project_template):
        remote_file = remote_file_template.format(**entry)
        extras = {
            'target_filename': remote_file,
        }
        commit_message = commit_message_template.format(GL=extras, **entry)

        local_file = local_file_template.format(**entry)
        try:
            local_file_content = pathlib.Path(local_file).read_text()
        except FileNotFoundError:
            if skip_missing_file:
                logger.error("Skipping %s as %s is missing.", project.path_with_namespace, local_file)
                continue
            else:
                raise

        commit_needed = force_commit
        already_exists = False
        if not force_commit:
            remote_file_content = mg.get_file_contents(glb, project, branch, remote_file)
            already_exists = remote_file_content is not None
            if already_exists:
                commit_needed = remote_file_content != local_file_content.encode('utf-8')
            else:
                commit_needed = True

        if commit_needed:
            if already_exists and only_once:
                logger.info(
                    "Not overwriting %s at %s.",
                    local_file, project.path_with_namespace
                )
            else:
                logger.info(
                    "Uploading %s to %s as %s",
                    local_file, project.path_with_namespace, remote_file
                )
            if not dry_run:
                mg.put_file(
                    glb, project, branch, remote_file,
                    local_file_content, not only_once, commit_message
                )
        else:
            logger.info("No change in %s at %s.", local_file, project.path_with_namespace)


@register_command('get-last-pipeline', 'Get last pipeline status')
def action_get_last_pipeline(
    glb: GitlabInstanceParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
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
    for _, project in entries.as_gitlab_projects(glb, project_template):
        pipelines = project.pipelines.list(iterator=True)
        last_pipeline = next(pipelines, None)

        if not last_pipeline:
            result[project.path_with_namespace] = {
                "status": "none"
            }
            pipeline_states_only.append("none")
            continue

        entry = {
            "status": last_pipeline.status,
            "id": last_pipeline.id,
            "commit": last_pipeline.sha,
            "jobs": [],
        }
        pipeline_states_only.append(last_pipeline.status)

        for job in last_pipeline.jobs.list(iterator=True):
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
        print(f"total: {states_len}")
    else:
        print(json.dumps(result, indent=4))


@register_command('get-pipeline-at-commit', 'Get pipeline status for a commit')
def action_get_pipeline_at_commit(
    glb: GitlabInstanceParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    commit_template: ActionParameter(
        'commit',
        default=None,
        metavar='COMMIT_WITH_FORMAT',
        help='Commit to read pipeline status at, formatted from CSV columns.'
    ),
):
    """
    Get pipeline status of multiple projects at or prior to specified
    commit while ignoring skipped pipelines.
    """

    result = {}
    for entry, project in entries.as_gitlab_projects(glb, project_template):
        commit_sha = commit_template.format(**entry) if commit_template else None

        found_commit = False
        found_pipeline = None
        for pipeline in project.pipelines.list(iterator=True):
            if not commit_sha:
                found_commit = True
            elif pipeline.sha == commit_sha:
                found_commit = True

            if not found_commit:
                continue

            if pipeline.status != "skipped":
                found_pipeline = pipeline
                break

        if not found_pipeline:
            entry = {
                "status": "none"
            }
        else:
            entry = {
                "status": found_pipeline.status,
                "id": found_pipeline.id,
                "commit": found_pipeline.sha,
                "jobs": [
                    {
                        "status": job.status,
                        "id": job.id,
                        "name": job.name,
                    }
                    for job in found_pipeline.jobs.list(iterator=True)
                ],
            }

        result[project.path_with_namespace] = entry

    print(json.dumps(result, indent=4))


@register_command('deadline-commit', 'Get commits for a deadline')
def action_deadline_commits(
    glb: GitlabInstanceParameter(),
    logger: LoggerParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter(),
    branch_template: ActionParameter(
        'branch',
        default='master',
        metavar='BRANCH_WITH_FORMAT',
        help='Branch name, defaults to master.'
    ),
    prefer_tag_template: ActionParameter(
        'prefer-tag',
        default=None,
        metavar='TAG_WITH_FORMAT',
        help='Prefer commit with this tag (but also before deadline).'
    ),
    deadline: DateTimeActionParameter(
        'deadline',
        default='now',
        metavar='YYYY-MM-DDTHH:MM:SSZ',
        help='Submission deadline (defaults to now).'
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

    output = open(output_filename, 'w') if output_filename else sys.stdout
    print(output_header, file=output)

    commit_filter = get_commit_author_email_filter(blacklist)
    for entry, project in entries.as_gitlab_projects(glb, project_template):
        prefer_tag = prefer_tag_template.format(**entry) if prefer_tag_template else None
        branch = branch_template.format(**entry)
        try:
            last_commit = mg.get_commit_before_deadline(
                glb, project, deadline, branch, commit_filter, prefer_tag
            )
        except gitlab.exceptions.GitlabGetError:
            class CommitMock:
                def __init__(self, commit_id):
                    self.id = commit_id

            last_commit = CommitMock('0000000000000000000000000000000000000000')

        logger.debug("%s at %s", project.path_with_namespace, last_commit.id)
        line = output_template.format(commit=last_commit, **entry)
        print(line, file=output)

    if output_filename:
        output.close()


@register_command('commit-stats', 'Get basic commit statistics')
def action_commit_stats(
    glb: GitlabInstanceParameter(),
    entries: ActionEntriesParameter(),
    project_template: RequiredProjectActionParameter()
):
    """
    Get basic added/removed lines for projects.
    """

    result = []
    for _, project in entries.as_gitlab_projects(glb, project_template):
        commits = project.commits.list(all=True, iterator=True)
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


@register_command('help-markdown', 'Generate Markdown documentation for all commands.')
def action_help_in_markdown(
    glb: GitlabInstanceParameter(),
    parser: IntrospectionParameter(),
):
    """
    Prints full help in Markdown format.
    """

    # Ensure stable formatting
    os.environ["COLUMNS"] = "80"

    print("# Teachers GitLab command help")
    print()
    print('This help is produced by calling help-markdown subcommand.')
    print()

    for cmd in get_registered_commands():
        print('\n\n## {}'.format(cmd['brief'] if cmd['brief'] else cmd['name']))
        print('\n```')
        parser.print_help(cmd['name'])
        print('```')


def init_logging(logging_level):
    """
    Initialize logging subsystem with a reasonable format.
    """

    logging.basicConfig(
        format='[%(asctime)s %(name)-25s %(levelname)7s] %(message)s',
        level=logging_level
    )


def main():
    """
    Main parses the arguments and only delegates the work.
    """

    locale.setlocale(locale.LC_ALL, '')

    cli = CommandParser()

    for cmd in get_registered_commands():
        cli.add_command(cmd['name'], cmd['func'])

    config = cli.parse_args(sys.argv[1:])

    if config.func is None:
        cli.print_help()
        return

    init_logging(logging.DEBUG if config.debug else logging.INFO)

    glb = cli.get_gitlab_instance()
    config.func(glb, config)


if __name__ == '__main__':
    main()
