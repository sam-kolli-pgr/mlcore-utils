import logging
import os
import pytest
import requests


logger = logging.getLogger(__name__)


class BL_Model(object):
    def __init__(self, model_name: str, version: str) -> None:
        self.model_name = model_name
        self.version = version

    def get_end_point(self, endpoint):
        return f"https://mlcore-nonprod.apps.nonprod.stratos.prci.com/v1/pipelines/{self.model_name}/versions/{self.version}/{endpoint}"
        # return f"https://blacklodge.apps.nonprod.stratos.prci.com/v1/pipelines/{self.model_name}/versions/{self.version}/{endpoint}"

    def call_endpoint(self, verb, endpoint, params=None, json_data=None):
        endpoint_url = self.get_end_point(endpoint)
        print(endpoint_url)
        headers = {"Content-Type": "application/json"}
        if verb == "get":
            return requests.get(
                url=endpoint_url, headers=headers, params=params, json=json_data
            )
        elif verb == "post":
            return requests.post(
                url=endpoint_url, headers=headers, params=params, json=json_data
            )
        else:
            print("Unknown http verb")


@pytest.fixture
def bl_model():
    version = "dev"
    name = "a123662"
    return BL_Model(name, version)


def test_run_1(bl_model):
    data = {"CreditAmount": 5000, "SavingsAccount": "rich", "Duration": 84}
    response = bl_model.call_endpoint("post", endpoint="run", json_data=data)
    print(response.status_code)
    print(response.text)
    assert response.status_code == 201


def test_status_1(bl_model):
    response = bl_model.call_endpoint("get", endpoint="status")
    print(response.status_code)
    print(response.text)
    assert response.status_code == 201
