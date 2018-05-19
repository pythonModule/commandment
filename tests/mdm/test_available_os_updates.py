import pytest
import os
import plistlib
from flask import Response
from tests.client import MDMClient
from commandment.mdm import CommandStatus
from commandment.models import Command, Device

TEST_DIR = os.path.realpath(os.path.dirname(__file__))


@pytest.fixture(scope='function')
def available_os_updates_command(session):
    """Creates an AvailableOSUpdates command that has been sent to the fixture device so that it can be marked
    acknowledged when the fake response comes in."""
    c = Command(
        uuid='00000000-1111-2222-3333-444455556666',
        request_type='AvailableOSUpdates',
        status=CommandStatus.Sent.value,
        parameters={},
    )
    session.add(c)
    session.commit()


@pytest.mark.usefixtures("device", "available_os_updates_command")
class TestAvailableOSUpdates:

    def test_available_os_updates_response(self, client: MDMClient, available_os_updates_request: str, session):
        response: Response = client.put('/mdm', data=available_os_updates_request, content_type='text/xml')
        assert response.status_code != 410
        assert response.status_code == 200

        d: Device = session.query(Device).filter(Device.udid == '00000000-1111-2222-3333-444455556666').one()
        updates = d.available_os_updates

        plist = plistlib.loads(available_os_updates_request.encode('utf8'))
        assert len(updates) == len(plist['AvailableOSUpdates'])
