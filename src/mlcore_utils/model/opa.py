import requests

from attrs import define, field

from mlcore_utils.model.blacklodge import Blacklodge_User
from mlcore_utils.model.common import Runtime_Environment, Runtime_Environment_Detector


@define
class Opa_Handler(object):
    logger = field()

    def does_user_have_permission(
        self, blacklodge_user: Blacklodge_User, object_name: str
    ) -> bool:
        request_data = {
            "input": {
                "user": blacklodge_user.lan_id,
                "roles": [blacklodge_user.custom_groups[0].upper()],
                "object": object_name,
            }
        }

        r = requests.post(
            "http://localhost:8181/v1/data", json=request_data, timeout=2, verify=False
        )
        if "app" not in r.json().get("result", {}):
            self.logger.error(
                "%s : %s : Exception while reading bundle file",
                blacklodge_user.lan_id,
                object_name,
            )
            raise PermissionError(
                "Error, couldn't authenticate user, Bundle file couldn't be read. Please contact the MLCore administrators at mlcore@progressive.com"
            )

        return (
            r.json()
            .get("result", {})
            .get("app", {})
            .get("registry", {})
            .get("allow", False)
        )


@define
class Opa_Bypass_Handler(object):
    logger = field()

    def does_user_have_permission(
        self, blacklodge_user: Blacklodge_User, object_name: str
    ) -> bool:
        return True


def get_opa_handler(logger, get_bypass_handler: bool = False):
    if get_bypass_handler == True:
        return Opa_Bypass_Handler
    else:
        return Opa_Handler


def get_opa_handler_env_based(logger):
    detected_environment = Runtime_Environment_Detector.detect()
    if detected_environment == Runtime_Environment.CLOUD9:
        logger.info(f"Running in {detected_environment.value}. Returning Opa_Handler")
        return Opa_Handler(logger)
    elif (
        detected_environment == Runtime_Environment.LOCAL_MAC
        or detected_environment == Runtime_Environment.LOCAL_DOCKER
    ):
        logger.info(
            f"Running in {detected_environment.value}. Returning Opa_ByPass_Handler"
        )
        return Opa_Bypass_Handler(logger)
    elif detected_environment == Runtime_Environment.STRATOS:
        logger.info(f"Running in {detected_environment.value}. Returning Opa_Handler")
        return Opa_Handler(logger)
    else:
        raise Exception(
            "Cannot get opa_handler for runtime " + detected_environment.name
        )
