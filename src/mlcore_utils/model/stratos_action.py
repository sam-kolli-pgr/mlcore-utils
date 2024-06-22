from attr import asdict, define, field
from mlcore_utils.model.common import Http_Method
from mlcore_utils.model.stratos_api import Stratos_Api_Caller
from mlcore_utils.model.stratos_interface import Stratos_ContainerBuild_Metadata_V1


@define
class Stratos_Container_Builder(object):
    stratos_api_caller: Stratos_Api_Caller = field()

    def build_container(self, containerbuild_data: Stratos_ContainerBuild_Metadata_V1):
        json_data = asdict(containerbuild_data)
        response = self.stratos_api_caller.call_api(
            http_method=Http_Method.POST,
            endpoint="containerbuild",
            json_data=json_data,
        )
        if response.status_code == 200:
            commit_sha = response.json()["commit_sha"]
            # status_response_url = f"{self.stratos_api_caller.stratos_url}/containerbuild/{commit_sha}/run-status"
            status_response_url = f"containerbuild/{commit_sha}/run-status"
            self.stratos_api_caller.call_status_url_and_await(status_response_url)
