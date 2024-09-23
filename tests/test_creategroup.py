
import logging

import teachers_gitlab.main

def test_creategroup(mock_gitlab):
    # First entry already exists, second must be created
    entries = [
        {'parent': 'common', 'path': 'able', 'name': 'One'},
        {'parent': 'common', 'path': 'baker', 'name': 'Two'},
    ]

    mock_gitlab.on_api_get(
        'groups/course%2Fcommon',
        response_json={
            'id': 123,
            'name': 'Parent group',
            'path': 'common',
            'full_path': 'course/common'
        }
    )
    mock_gitlab.on_api_get(
        'groups/course%2Fcommon%2Fable',
        response_json={
            'id': 456,
            'name': 'Group One - able',
            'path': 'able',
            'full_path': 'course/common/able'
        }
    )
    mock_gitlab.on_api_get(
        'groups/course%2Fcommon%2Fbaker',
        response_404=True
    )
    mock_gitlab.on_api_post(
        'groups',
        request_json={
            'name': 'Group Two - baker',
            'path': 'baker',
            'parent_id': 123
        },
        response_json={}
    )

    mock_gitlab.report_unknown()

    teachers_gitlab.main.create_group(
        mock_gitlab.get_python_gitlab(),
        logging.getLogger("unprotect"),
        teachers_gitlab.main.ActionEntries(entries),
        'Group {name} - {path}',
        'course/{parent}/{path}'
    )
