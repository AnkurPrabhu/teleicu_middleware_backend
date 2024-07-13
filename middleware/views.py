from datetime import datetime
import json
from typing import Dict, List, Optional
from uuid import UUID
import requests
from middleware.tasks import retrieve_asset_config
from middleware.utils.observation_utils import update_stored_observations
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.response import Response
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings


from .utils.utils import group_by

from .types.observations import DeviceID


from middleware.types.observations import (
    Observation,
    ObservationID,
    ObservationList,
)

from .authentication import CareAuthentication

active_devices: List[str] = []


# As we dont get the blood pressure data every single time
# in order to get continuous data we take the previous data
# to store previous value of blood pressure per device_id
blood_pressure_data: Dict[DeviceID, Observation] = {}


@api_view(["POST"])
def get_mock_request_list(request):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "send_mock_req", {"type": "send_mock_req", "message": request.data}
    )
    return Response({"result": "Received request"}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([CareAuthentication])
def sample_authentication(request):
    return Response({"result": "Authenticated"}, status=status.HTTP_200_OK)


@api_view(["GET"])
def test_route(request):
    return Response({"result": "healthy"}, status=status.HTTP_200_OK)


@api_view(["POST"])
def update_observations(request):
    data = flatten_observations(request.data)
    observation_data: List[Observation] = ObservationList.model_validate(data).root

    # TODO
    # addStatusData

    # store observations in redis
    update_stored_observations(observation_data)

    # store last blood pressure value for devices
    update_blood_pressure(observation_data)

    channel_layer = get_channel_layer()
    grouped_observations = group_by(data=observation_data, key="device_id")
    for device_id, observation_list in grouped_observations.items():
        last_blood_pressure_data = blood_pressure_data.get(device_id, None)
        if last_blood_pressure_data:
            observation_list.append(last_blood_pressure_data)

        async_to_sync(channel_layer.group_send)(
            f"ip_{device_id}",
            {
                "type": "send_observation",
                "message": [
                    observation.model_dump(mode="json", by_alias=True)
                    for observation in observation_list
                ],
            },
        )

    return Response({"result": "Successful"}, status=status.HTTP_200_OK)


def update_blood_pressure(observations: List[Observation]):
    for observation in observations:
        if observation.observation_id == ObservationID.BLOOD_PRESSURE:
            blood_pressure_data[observation.device_id] = observation


def flatten_observations(observations):
    if isinstance(observations, list):
        flattened_list = []
        for observation in observations:
            flattened_list.extend(flatten_observations(observation))
        return flattened_list
    else:
        return [observations]