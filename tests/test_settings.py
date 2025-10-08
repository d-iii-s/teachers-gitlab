import logging

import teachers_gitlab.main as tg


def test_project_settings_changing_everything(mock_gitlab):
    entries = [
        {
            'login': 'alpha',
            'name': 'Alpha Able'
        },
    ]

    mock_gitlab.register_project(42, 'student/alpha',
        mr_default_target_self=False,
        description='',
        squash_option="default_off"
    )

    mock_gitlab.on_api_put(
        'projects/42',
        request_json= {
            'mr_default_target_self': True,
            'description': 'Semestral project for Alpha Able',
            'squash_option': 'never',
        },
        response_json={
            'id': 42,
            'path_with_namespace': 'student/alpha',
        }
    )

    mock_gitlab.report_unknown()

    tg.action_project_settings(
        mock_gitlab.get_python_gitlab(),
        logging.getLogger('settings'),
        tg.ActionEntries(entries),
        False,
        'student/{login}',
        'self',
        'Semestral project for {name}',
        'never'
    )



def test_project_settings_changing_only_name(mock_gitlab):
    entries = [
        {'login': 'beta'},
    ]

    mock_gitlab.register_project(38, 'student/beta',
        mr_default_target_self=False,
        description='',
        squash_option="default_off"
    )
    mock_gitlab.on_api_put(
        'projects/38',
        request_json= {
            'description': 'The best project',
        },
        response_json={
            'id': 38,
            'path_with_namespace': 'student/beta',
        }
    )

    mock_gitlab.report_unknown()


    tg.action_project_settings(
        mock_gitlab.get_python_gitlab(),
        logging.getLogger('settings'),
        tg.ActionEntries(entries),
        False,
        'student/{login}',
        None,
        'The best project',
        'default_off'
    )
